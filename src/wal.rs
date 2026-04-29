use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use anyhow::Context;
use crc::{Crc, CRC_64_ECMA_182};
use serde::{Deserialize, Serialize};
use tokio::io::AsyncWriteExt;

pub const DATA_INGESTED: u32 = 200;
pub const INFERENCE_STARTED: u32 = 201;
pub const INFERENCE_COMPLETED: u32 = 202;
pub const SIGNAL_PRODUCED: u32 = 203;
pub const SIGNAL_PUBLISHED: u32 = 204;
pub const CHECKPOINT: u32 = 205;
pub const SESSION_START: u32 = 206;
pub const SESSION_STOP: u32 = 207;
pub const INGEST_ERROR: u32 = 208;
pub const INFERENCE_ERROR: u32 = 209;

const CRC: Crc<u64> = Crc::<u64>::new(&CRC_64_ECMA_182);
const MAX_SEGMENT_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalDataIngested {
    pub source: String,
    pub timestamp: u64,
    pub feature_count: u64,
    pub feature_vector_hash: String,
    pub ingest_duration_ms: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalInferenceStarted {
    pub session_id: String,
    pub model_id: String,
    pub model_version: String,
    pub input_hash: String,
    pub data_sources: Vec<String>,
    pub feature_count: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalInferenceCompleted {
    pub session_id: String,
    pub model_id: String,
    pub regime_class: String,
    pub confidence: f64,
    pub reasoning_summary_hash: String,
    pub inference_duration_ms: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalSignalProduced {
    pub market_id: String,
    pub direction: String,
    pub magnitude: f64,
    pub conviction: String,
    pub horizon_days: u32,
    pub expires_at: u64,
    pub regime_source: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalSignalPublished {
    pub signal_ids: Vec<String>,
    pub published_to: String,
    pub ack_received: bool,
    pub wal_sequence: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalCheckpoint {
    pub session_id: String,
    pub last_processed: HashMap<String, u64>,
    pub regime_history_count: u64,
    pub signals_produced_count: u64,
    pub model_version: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalSessionStart {
    pub session_id: String,
    pub argus_version: String,
    pub model_configs: Vec<String>,
    pub data_sources: Vec<String>,
    pub reason: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalSessionStop {
    pub session_id: String,
    pub reason: String,
    pub final_sequence: u64,
    pub signals_produced: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalIngestError {
    pub source: String,
    pub error: String,
    pub will_retry: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct WalInferenceError {
    pub model_id: String,
    pub error: String,
    pub input_hash: String,
}

#[derive(Debug, Clone)]
pub struct WalEntry {
    pub sequence: u64,
    pub timestamp_ns: u64,
    pub entry_type: u32,
    pub payload: Vec<u8>,
}

pub struct ArgusWal {
    dir: PathBuf,
    file: tokio::sync::Mutex<tokio::fs::File>,
    sequence: Arc<AtomicU64>,
    segment_bytes: tokio::sync::Mutex<u64>,
    max_segment_bytes: u64,
}

impl ArgusWal {
    pub async fn open(session_dir: &Path) -> anyhow::Result<Self> {
        std::fs::create_dir_all(session_dir)?;

        let (file, start_seq, segment_bytes) = Self::open_latest_segment(session_dir).await?;

        Ok(Self {
            dir: session_dir.to_path_buf(),
            file: tokio::sync::Mutex::new(file),
            sequence: Arc::new(AtomicU64::new(start_seq)),
            segment_bytes: tokio::sync::Mutex::new(segment_bytes),
            max_segment_bytes: MAX_SEGMENT_BYTES,
        })
    }

    async fn open_latest_segment(dir: &Path) -> anyhow::Result<(tokio::fs::File, u64, u64)> {
        let mut max_seg: Option<u32> = None;
        if let Ok(mut rd) = tokio::fs::read_dir(dir).await {
            while let Ok(Some(entry)) = rd.next_entry().await {
                let name = entry.file_name();
                let s = name.to_string_lossy();
                if s.starts_with("argus_wal_") && s.ends_with(".log") {
                    if let Ok(n) = s[10..s.len() - 4].parse::<u32>() {
                        max_seg = Some(max_seg.map_or(n, |m: u32| m.max(n)));
                    }
                }
            }
        }

        let seg_num = max_seg.unwrap_or(0);
        let path = dir.join(format!("argus_wal_{:04}.log", seg_num));

        let file = tokio::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .await?;

        let segment_bytes = file.metadata().await?.len();

        let start_seq = if max_seg.is_some() && segment_bytes > 0 {
            Self::scan_last_seq_sync(&path)?
        } else {
            0
        };

        Ok((file, start_seq, segment_bytes))
    }

    fn scan_last_seq_sync(path: &Path) -> anyhow::Result<u64> {
        let data = std::fs::read(path)?;
        let mut last_seq = 0u64;
        let mut pos = 0usize;
        while pos + 32 <= data.len() {
            let seq = u64::from_be_bytes(data[pos..pos + 8].try_into()?);
            let payload_len = u32::from_be_bytes(data[pos + 20..pos + 24].try_into()?) as usize;
            let frame_len = 32 + payload_len;
            if pos + frame_len > data.len() {
                break;
            }
            last_seq = seq;
            pos += frame_len;
        }
        Ok(last_seq)
    }

    pub async fn append<T: Serialize>(&self, entry_type: u32, payload: &T) -> anyhow::Result<u64> {
        let payload_bytes = rmp_serde::to_vec(payload)?;
        let seq = self.sequence.fetch_add(1, Ordering::SeqCst) + 1;
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_nanos() as u64;

        let mut frame = Vec::with_capacity(32 + payload_bytes.len());
        frame.extend_from_slice(&seq.to_be_bytes());
        frame.extend_from_slice(&ts.to_be_bytes());
        frame.extend_from_slice(&entry_type.to_be_bytes());
        frame.extend_from_slice(&(payload_bytes.len() as u32).to_be_bytes());
        frame.extend_from_slice(&payload_bytes);

        let checksum = CRC.checksum(&frame);
        frame.extend_from_slice(&checksum.to_be_bytes());

        let mut file = self.file.lock().await;
        file.write_all(&frame).await?;
        file.flush().await?;

        let mut seg_bytes = self.segment_bytes.lock().await;
        *seg_bytes += frame.len() as u64;

        Ok(seq)
    }

    pub async fn rotate(&self) -> anyhow::Result<()> {
        let seg_bytes = *self.segment_bytes.lock().await;
        if seg_bytes < self.max_segment_bytes {
            return Ok(());
        }

        let mut entries = vec![];
        if let Ok(mut rd) = tokio::fs::read_dir(&self.dir).await {
            while let Ok(Some(e)) = rd.next_entry().await {
                let name = e.file_name();
                let s = name.to_string_lossy().to_string();
                if s.starts_with("argus_wal_") && s.ends_with(".log") {
                    if let Ok(n) = s[10..s.len() - 4].parse::<u32>() {
                        entries.push(n);
                    }
                }
            }
        }
        let next_seg = entries.iter().max().copied().unwrap_or(0) + 1;
        let path = self.dir.join(format!("argus_wal_{:04}.log", next_seg));

        let new_file = tokio::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .await?;

        let mut file = self.file.lock().await;
        *file = new_file;
        let mut seg_bytes = self.segment_bytes.lock().await;
        *seg_bytes = 0;

        Ok(())
    }

    pub fn read_from(path: &Path, after_seq: u64) -> anyhow::Result<Vec<WalEntry>> {
        let data = std::fs::read(path).context("reading WAL file")?;
        let mut entries = vec![];
        let mut pos = 0usize;

        while pos + 32 <= data.len() {
            let seq = u64::from_be_bytes(data[pos..pos + 8].try_into()?);
            let ts = u64::from_be_bytes(data[pos + 8..pos + 16].try_into()?);
            let entry_type = u32::from_be_bytes(data[pos + 16..pos + 20].try_into()?);
            let payload_len = u32::from_be_bytes(data[pos + 20..pos + 24].try_into()?) as usize;
            let frame_len = 32 + payload_len;

            if pos + frame_len > data.len() {
                break;
            }

            let payload = data[pos + 24..pos + 24 + payload_len].to_vec();
            let stored_crc = u64::from_be_bytes(
                data[pos + 24 + payload_len..pos + frame_len].try_into()?,
            );
            let computed_crc = CRC.checksum(&data[pos..pos + 24 + payload_len]);

            if stored_crc != computed_crc {
                anyhow::bail!("CRC mismatch at seq={}", seq);
            }

            if seq > after_seq {
                entries.push(WalEntry {
                    sequence: seq,
                    timestamp_ns: ts,
                    entry_type,
                    payload,
                });
            }

            pos += frame_len;
        }

        Ok(entries)
    }

    pub async fn find_last_checkpoint(dir: &Path) -> anyhow::Result<Option<(u64, WalCheckpoint)>> {
        let mut seg_paths: Vec<PathBuf> = vec![];
        if let Ok(mut rd) = tokio::fs::read_dir(dir).await {
            while let Ok(Some(e)) = rd.next_entry().await {
                let name = e.file_name();
                let s = name.to_string_lossy().to_string();
                if s.starts_with("argus_wal_") && s.ends_with(".log") {
                    seg_paths.push(dir.join(s));
                }
            }
        }
        seg_paths.sort();

        let mut last: Option<(u64, WalCheckpoint)> = None;
        for path in seg_paths {
            let entries = match Self::read_from(&path, 0) {
                Ok(e) => e,
                Err(_) => continue,
            };
            for entry in entries {
                if entry.entry_type == CHECKPOINT {
                    if let Ok(cp) = rmp_serde::from_slice::<WalCheckpoint>(&entry.payload) {
                        last = Some((entry.sequence, cp));
                    }
                }
            }
        }

        Ok(last)
    }

    pub fn current_sequence(&self) -> u64 {
        self.sequence.load(Ordering::SeqCst)
    }
}

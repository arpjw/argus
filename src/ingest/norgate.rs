use std::path::PathBuf;

use async_trait::async_trait;

use super::{DataPayload, DataSource};
use crate::utils::current_time_ms;

pub struct NorgateSource {
    pub data_dir: PathBuf,
    pub symbols: Vec<String>,
}

impl NorgateSource {
    pub fn new(data_dir: Option<PathBuf>) -> Self {
        Self {
            data_dir: data_dir.unwrap_or_else(|| PathBuf::from("/nonexistent")),
            symbols: vec!["ES".into(), "NQ".into(), "GC".into(), "CL".into(), "DX".into()],
        }
    }
}

#[async_trait]
impl DataSource for NorgateSource {
    fn source_id(&self) -> &str {
        "NORGATE"
    }

    async fn fetch_latest(&self, _since: Option<u64>) -> anyhow::Result<DataPayload> {
        // TODO: read local Norgate OHLCV files; compute momentum + realized vol
        // Returns empty payload when data_dir doesn't exist
        if !self.is_available() {
            return Ok(DataPayload {
                source_id: self.source_id().to_string(),
                timestamp: current_time_ms(),
                features: vec![],
                raw_count: 0,
            });
        }
        todo!("Norgate ingestion — implement when local data dir available")
    }

    fn is_available(&self) -> bool {
        self.data_dir.exists()
    }
}

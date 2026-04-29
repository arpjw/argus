use std::sync::Arc;

use tokio::sync::RwLock;

use crate::checkpoint::{ArgusCheckpoint, RegimeAssessment, SignalRecord};
use crate::config::ArgusConfig;
use crate::fsm::{ArgusEvent, ArgusFsm, ArgusState};
use crate::ingest::DataSource;
use crate::ingest::fred::FredSource;
use crate::ingest::kalshi::KalshiSource;
use crate::ingest::news::NewsSource;
use crate::ingest::norgate::NorgateSource;
use crate::inference::RegimeClassifier;
use crate::inference::classifier::PlaceholderClassifier;
use crate::publish::{FilePublisher, MonolithStrategyPublisher, SignalPublisher, StdoutPublisher};
use crate::signals::SignalProducer;
use crate::utils::{current_time_ms, sha256_hex};
use crate::wal::{
    ArgusWal, WalCheckpoint, WalDataIngested, WalInferenceCompleted, WalInferenceError,
    WalInferenceStarted, WalIngestError, WalSessionStart, WalSessionStop, WalSignalProduced,
    WalSignalPublished, CHECKPOINT, DATA_INGESTED, INFERENCE_COMPLETED, INFERENCE_ERROR,
    INFERENCE_STARTED, INGEST_ERROR, SESSION_START, SESSION_STOP, SIGNAL_PRODUCED,
    SIGNAL_PUBLISHED,
};

pub struct ArgusSession {
    config: ArgusConfig,
    wal: Arc<ArgusWal>,
    checkpoint: Arc<RwLock<ArgusCheckpoint>>,
    pub fsm: ArgusFsm,
    data_sources: Vec<Box<dyn DataSource>>,
    classifier: Box<dyn RegimeClassifier>,
    signal_producer: SignalProducer,
    publisher: Box<dyn SignalPublisher>,
    ticks_since_checkpoint: u64,
}

impl ArgusSession {
    pub async fn new(config: ArgusConfig) -> anyhow::Result<Self> {
        config.validate()?;
        std::fs::create_dir_all(&config.session_dir)?;

        let wal = Arc::new(ArgusWal::open(&config.session_dir).await?);

        let (checkpoint, reason) =
            match ArgusWal::find_last_checkpoint(&config.session_dir).await? {
                Some((_seq, cp_meta)) => {
                    let mut cp = ArgusCheckpoint::new(cp_meta.session_id.clone());
                    cp.last_processed = cp_meta.last_processed;
                    cp.signals_produced_total = cp_meta.signals_produced_count;
                    (cp, "recovery")
                }
                None => {
                    let session_id = uuid::Uuid::new_v4().to_string();
                    (ArgusCheckpoint::new(session_id), "fresh")
                }
            };

        wal.append(
            SESSION_START,
            &WalSessionStart {
                session_id: checkpoint.session_id.clone(),
                argus_version: env!("CARGO_PKG_VERSION").to_string(),
                model_configs: config.classifier_id.clone(),
                data_sources: config.data_sources.clone(),
                reason: reason.to_string(),
            },
        )
        .await?;

        let data_sources = build_data_sources(&config);

        let classifier: Box<dyn RegimeClassifier> =
            Box::new(PlaceholderClassifier::new());

        let publisher = build_publisher(&config);

        let fsm = ArgusFsm::new(wal.clone(), checkpoint.session_id.clone());

        Ok(Self {
            config,
            wal,
            checkpoint: Arc::new(RwLock::new(checkpoint)),
            fsm,
            data_sources,
            classifier,
            signal_producer: SignalProducer::new(),
            publisher,
            ticks_since_checkpoint: 0,
        })
    }

    pub async fn run(&mut self) -> anyhow::Result<()> {
        self.fsm.transition(ArgusEvent::Start).await?;

        loop {
            match self.fsm.state.clone() {
                ArgusState::IngestingData => {
                    self.ingest_all_sources().await?;
                    self.fsm.transition(ArgusEvent::AllSourcesIngested).await?;
                }

                ArgusState::RunningClassifier => {
                    match self.run_classifier().await {
                        Ok(classification) => {
                            let regime = classification.regime_class.clone();
                            let conf = classification.confidence;
                            let session_id = self.checkpoint.read().await.session_id.clone();

                            self.wal
                                .append(
                                    INFERENCE_COMPLETED,
                                    &WalInferenceCompleted {
                                        session_id: session_id.clone(),
                                        model_id: self.classifier.model_id().to_string(),
                                        regime_class: regime.clone(),
                                        confidence: conf,
                                        reasoning_summary_hash: "placeholder".to_string(),
                                        inference_duration_ms: classification.inference_duration_ms,
                                    },
                                )
                                .await?;

                            let assessment = RegimeAssessment {
                                regime_class: regime.clone(),
                                confidence: conf,
                                horizon_days: classification.horizon_days,
                                produced_at: current_time_ms(),
                                session_id,
                                model_version: self.classifier.model_version().to_string(),
                                wal_sequence: self.wal.current_sequence(),
                            };
                            self.checkpoint
                                .write()
                                .await
                                .apply_regime_assessment(assessment);

                            self.fsm
                                .transition(ArgusEvent::ClassificationComplete {
                                    regime: classification.regime_class,
                                    confidence: classification.confidence,
                                })
                                .await?;
                        }
                        Err(e) => {
                            self.wal
                                .append(
                                    INFERENCE_ERROR,
                                    &WalInferenceError {
                                        model_id: self.classifier.model_id().to_string(),
                                        error: e.to_string(),
                                        input_hash: "unknown".to_string(),
                                    },
                                )
                                .await?;
                            self.fsm
                                .transition(ArgusEvent::InferenceError {
                                    model: self.classifier.model_id().to_string(),
                                    error: e.to_string(),
                                })
                                .await?;
                        }
                    }
                }

                ArgusState::RunningGenerative => {
                    self.fsm.transition(ArgusEvent::GenerativeComplete).await?;
                }

                ArgusState::ProducingSignals => {
                    let signals = {
                        let cp = self.checkpoint.read().await;
                        if let Some(regime) = cp.latest_regime() {
                            self.signal_producer.produce(regime, &self.config)
                        } else {
                            vec![]
                        }
                    };

                    let count = signals.len();

                    for signal in &signals {
                        let seq = self
                            .wal
                            .append(
                                SIGNAL_PRODUCED,
                                &WalSignalProduced {
                                    market_id: signal.market_id.clone(),
                                    direction: signal.direction.clone(),
                                    magnitude: signal.magnitude,
                                    conviction: signal.conviction.clone(),
                                    horizon_days: 3,
                                    expires_at: signal.expires_at,
                                    regime_source: signal.regime_source.clone(),
                                },
                            )
                            .await?;

                        let mut s = signal.clone();
                        s.wal_sequence = seq;
                        self.checkpoint.write().await.apply_signal_produced(s);
                    }

                    self.fsm
                        .transition(ArgusEvent::SignalsProduced { count })
                        .await?;
                }

                ArgusState::PublishingSignals => {
                    let signals: Vec<SignalRecord> = self
                        .checkpoint
                        .read()
                        .await
                        .active_signals
                        .values()
                        .filter(|s| !s.published)
                        .cloned()
                        .collect();

                    if !signals.is_empty() {
                        self.publisher.publish(&signals).await?;

                        let ids: Vec<String> = signals.iter().map(|s| s.id.clone()).collect();
                        self.wal
                            .append(
                                SIGNAL_PUBLISHED,
                                &WalSignalPublished {
                                    signal_ids: ids,
                                    published_to: self.publisher.publisher_id().to_string(),
                                    ack_received: true,
                                    wal_sequence: self.wal.current_sequence(),
                                },
                            )
                            .await?;

                        let mut cp = self.checkpoint.write().await;
                        for signal in signals {
                            if let Some(s) = cp.active_signals.get_mut(&signal.id) {
                                s.published = true;
                            }
                        }
                    }

                    self.fsm.transition(ArgusEvent::SignalsPublished).await?;
                }

                ArgusState::WaitingForNextTick => {
                    self.ticks_since_checkpoint += 1;
                    if self.ticks_since_checkpoint >= self.config.checkpoint_interval_ticks {
                        self.write_checkpoint().await?;
                        self.ticks_since_checkpoint = 0;
                    }

                    let tick_ms = self.config.tick_interval_ms;
                    tokio::time::sleep(tokio::time::Duration::from_millis(tick_ms)).await;
                    self.fsm.transition(ArgusEvent::TickElapsed).await?;
                }

                ArgusState::Stopping => {
                    self.write_checkpoint().await?;
                    let (session_id, signals_total) = {
                        let cp = self.checkpoint.read().await;
                        (cp.session_id.clone(), cp.signals_produced_total)
                    };
                    self.wal
                        .append(
                            SESSION_STOP,
                            &WalSessionStop {
                                session_id,
                                reason: "clean".to_string(),
                                final_sequence: self.wal.current_sequence(),
                                signals_produced: signals_total,
                            },
                        )
                        .await?;
                    break;
                }

                _ => {
                    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
                }
            }
        }

        Ok(())
    }

    async fn ingest_all_sources(&mut self) -> anyhow::Result<()> {
        for source in &self.data_sources {
            if !source.is_available() {
                continue;
            }
            let since = self
                .checkpoint
                .read()
                .await
                .last_processed
                .get(source.source_id())
                .copied();

            let start = std::time::Instant::now();
            match source.fetch_latest(since).await {
                Ok(payload) => {
                    let duration_ms = start.elapsed().as_millis() as u64;
                    let feature_hash = sha256_hex(
                        payload
                            .features
                            .iter()
                            .map(|f| f.value.to_string())
                            .collect::<Vec<_>>()
                            .join(",")
                            .as_bytes(),
                    );
                    self.wal
                        .append(
                            DATA_INGESTED,
                            &WalDataIngested {
                                source: payload.source_id.clone(),
                                timestamp: payload.timestamp,
                                feature_count: payload.features.len() as u64,
                                feature_vector_hash: feature_hash,
                                ingest_duration_ms: duration_ms,
                            },
                        )
                        .await?;
                    self.checkpoint
                        .write()
                        .await
                        .last_processed
                        .insert(payload.source_id, payload.timestamp);
                }
                Err(e) => {
                    self.wal
                        .append(
                            INGEST_ERROR,
                            &WalIngestError {
                                source: source.source_id().to_string(),
                                error: e.to_string(),
                                will_retry: true,
                            },
                        )
                        .await?;
                    self.fsm
                        .transition(ArgusEvent::IngestError {
                            source: source.source_id().to_string(),
                            error: e.to_string(),
                        })
                        .await?;
                }
            }
        }
        Ok(())
    }

    async fn run_classifier(&self) -> anyhow::Result<crate::inference::RegimeClassification> {
        let session_id = self.checkpoint.read().await.session_id.clone();
        let features = vec![];

        self.wal
            .append(
                INFERENCE_STARTED,
                &WalInferenceStarted {
                    session_id,
                    model_id: self.classifier.model_id().to_string(),
                    model_version: self.classifier.model_version().to_string(),
                    input_hash: crate::inference::classifier::hash_features(&features),
                    data_sources: self.config.data_sources.clone(),
                    feature_count: features.len() as u64,
                },
            )
            .await?;

        self.classifier.classify(features).await
    }

    async fn write_checkpoint(&self) -> anyhow::Result<()> {
        let cp = self.checkpoint.read().await;
        let meta = WalCheckpoint {
            session_id: cp.session_id.clone(),
            last_processed: cp.last_processed.clone(),
            regime_history_count: cp.regime_history.len() as u64,
            signals_produced_count: cp.signals_produced_total,
            model_version: self
                .classifier
                .model_version()
                .to_string(),
        };
        drop(cp);

        self.wal.append(CHECKPOINT, &meta).await?;

        let cp_path = self
            .config
            .session_dir
            .join("checkpoint.json");
        let cp = self.checkpoint.read().await;
        let json = serde_json::to_string_pretty(&*cp)?;
        tokio::fs::write(&cp_path, json).await?;

        self.wal.rotate().await?;
        Ok(())
    }
}

fn build_data_sources(config: &ArgusConfig) -> Vec<Box<dyn DataSource>> {
    let mut sources: Vec<Box<dyn DataSource>> = vec![];
    for id in &config.data_sources {
        match id.as_str() {
            "FRED" => sources.push(Box::new(FredSource::new())),
            "KALSHI" => sources.push(Box::new(KalshiSource::new())),
            "NEWS" => sources.push(Box::new(NewsSource::new())),
            "NORGATE" => sources.push(Box::new(NorgateSource::new(
                config.norgate_data_dir.clone(),
            ))),
            other => tracing::warn!("unknown data source: {}", other),
        }
    }
    sources
}

fn build_publisher(config: &ArgusConfig) -> Box<dyn SignalPublisher> {
    match config.publisher.as_str() {
        "file" => Box::new(FilePublisher {
            output_path: config
                .output_path
                .clone()
                .unwrap_or_else(|| config.session_dir.join("signals.jsonl")),
        }),
        "monolith" => Box::new(MonolithStrategyPublisher {
            endpoint: String::new(),
            api_key: String::new(),
        }),
        _ => Box::new(StdoutPublisher),
    }
}

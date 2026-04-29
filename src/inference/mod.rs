pub mod classifier;
pub mod generative;

use std::collections::HashMap;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use crate::ingest::Feature;

#[async_trait]
pub trait RegimeClassifier: Send + Sync {
    fn model_id(&self) -> &str;
    fn model_version(&self) -> &str;

    async fn classify(&self, features: Vec<Feature>) -> anyhow::Result<RegimeClassification>;
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegimeClassification {
    pub regime_class: String,
    pub confidence: f64,
    pub horizon_days: u32,
    pub raw_probabilities: HashMap<String, f64>,
    pub model_id: String,
    pub model_version: String,
    pub input_hash: String,
    pub inference_duration_ms: u64,
}

pub const REGIME_CLASSES: &[&str] = &[
    "risk_on_growth",
    "risk_off_dollar_strength",
    "inflation_breakout",
    "deflation_risk",
    "neutral_drift",
    "geopolitical_shock",
];

use std::collections::HashMap;
use std::path::PathBuf;

use async_trait::async_trait;

use super::{RegimeClassification, RegimeClassifier};
use crate::ingest::Feature;
use crate::utils::sha256_hex;

pub struct PlaceholderClassifier {
    pub model_id: String,
}

impl PlaceholderClassifier {
    pub fn new() -> Self {
        Self {
            model_id: "argus-placeholder".to_string(),
        }
    }
}

#[async_trait]
impl RegimeClassifier for PlaceholderClassifier {
    fn model_id(&self) -> &str {
        &self.model_id
    }

    fn model_version(&self) -> &str {
        "placeholder-0.1.0"
    }

    async fn classify(&self, features: Vec<Feature>) -> anyhow::Result<RegimeClassification> {
        tracing::warn!("PlaceholderClassifier in use — no real inference");
        Ok(RegimeClassification {
            regime_class: "neutral_drift".to_string(),
            confidence: 0.5,
            horizon_days: 3,
            raw_probabilities: HashMap::new(),
            model_id: self.model_id.clone(),
            model_version: "placeholder-0.1.0".to_string(),
            input_hash: hash_features(&features),
            inference_duration_ms: 0,
        })
    }
}

pub struct LocalModelClassifier {
    pub model_path: PathBuf,
    pub model_id: String,
}

#[async_trait]
impl RegimeClassifier for LocalModelClassifier {
    fn model_id(&self) -> &str {
        &self.model_id
    }

    fn model_version(&self) -> &str {
        "local-0.1.0"
    }

    async fn classify(&self, _features: Vec<Feature>) -> anyhow::Result<RegimeClassification> {
        // TODO: integrate llama.cpp or ONNX runtime
        anyhow::bail!("LocalModelClassifier not yet implemented")
    }
}

pub fn hash_features(features: &[Feature]) -> String {
    let mut keys: Vec<&str> = features.iter().map(|f| f.key.as_str()).collect();
    keys.sort();
    sha256_hex(keys.join(",").as_bytes())
}

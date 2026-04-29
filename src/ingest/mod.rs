pub mod fred;
pub mod kalshi;
pub mod news;
pub mod norgate;

use std::collections::HashMap;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

#[async_trait]
pub trait DataSource: Send + Sync {
    fn source_id(&self) -> &str;

    async fn fetch_latest(&self, since: Option<u64>) -> anyhow::Result<DataPayload>;

    fn is_available(&self) -> bool;
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataPayload {
    pub source_id: String,
    pub timestamp: u64,
    pub features: Vec<Feature>,
    pub raw_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Feature {
    pub key: String,
    pub value: f64,
    pub timestamp: u64,
    pub metadata: HashMap<String, String>,
}

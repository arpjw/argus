use async_trait::async_trait;

use super::{DataPayload, DataSource};
use crate::utils::current_time_ms;

pub struct NewsSource {
    pub api_key: String,
    pub keywords: Vec<String>,
    pub max_articles: usize,
}

impl NewsSource {
    pub fn new() -> Self {
        Self {
            api_key: std::env::var("NEWS_API_KEY").unwrap_or_default(),
            keywords: vec![
                "Federal Reserve".into(),
                "inflation".into(),
                "GDP".into(),
            ],
            max_articles: 50,
        }
    }
}

#[async_trait]
impl DataSource for NewsSource {
    fn source_id(&self) -> &str {
        "NEWS"
    }

    async fn fetch_latest(&self, _since: Option<u64>) -> anyhow::Result<DataPayload> {
        // TODO: fetch headlines matching keywords; extract sentiment features
        // Returns empty payload when NEWS_API_KEY not set
        if !self.is_available() {
            return Ok(DataPayload {
                source_id: self.source_id().to_string(),
                timestamp: current_time_ms(),
                features: vec![],
                raw_count: 0,
            });
        }
        todo!("News ingestion — implement when NEWS_API_KEY available")
    }

    fn is_available(&self) -> bool {
        std::env::var("NEWS_API_KEY").is_ok()
    }
}

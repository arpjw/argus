use std::path::PathBuf;

use async_trait::async_trait;

use super::{DataPayload, DataSource};
use crate::utils::current_time_ms;

pub struct FredSource {
    pub api_key: String,
    pub series_ids: Vec<String>,
    pub base_url: String,
}

impl FredSource {
    pub fn new() -> Self {
        Self {
            api_key: std::env::var("FRED_API_KEY").unwrap_or_default(),
            series_ids: vec![
                "DFF".into(),
                "T10Y2Y".into(),
                "UNRATE".into(),
                "CPIAUCSL".into(),
                "DTWEXBGS".into(),
                "VIXCLS".into(),
            ],
            base_url: "https://api.stlouisfed.org/fred".into(),
        }
    }
}

#[async_trait]
impl DataSource for FredSource {
    fn source_id(&self) -> &str {
        "FRED"
    }

    async fn fetch_latest(&self, _since: Option<u64>) -> anyhow::Result<DataPayload> {
        // TODO: GET {base_url}/series/observations for each series_id
        // Returns empty payload when FRED_API_KEY not set
        if !self.is_available() {
            return Ok(DataPayload {
                source_id: self.source_id().to_string(),
                timestamp: current_time_ms(),
                features: vec![],
                raw_count: 0,
            });
        }
        todo!("FRED ingestion — implement when FRED_API_KEY available")
    }

    fn is_available(&self) -> bool {
        std::env::var("FRED_API_KEY").is_ok()
    }
}

use std::collections::HashMap;

use async_trait::async_trait;
use serde::Deserialize;

use super::{DataPayload, DataSource, Feature};
use crate::utils::current_time_ms;

pub struct KalshiSource {
    pub base_url: String,
    pub series_of_interest: Vec<String>,
}

impl KalshiSource {
    pub fn new() -> Self {
        Self {
            base_url: "https://trading-api.kalshi.com/trade-api/v2".into(),
            series_of_interest: vec![
                "KXFED".into(),
                "KXRECES".into(),
                "KXINFL".into(),
                "KXBTC".into(),
            ],
        }
    }
}

#[derive(Deserialize, Debug)]
struct KalshiMarketsResponse {
    markets: Vec<KalshiMarket>,
}

#[derive(Deserialize, Debug)]
struct KalshiMarket {
    ticker: String,
    yes_bid: Option<i64>,
    yes_ask: Option<i64>,
    volume: Option<i64>,
    last_price: Option<i64>,
}

#[async_trait]
impl DataSource for KalshiSource {
    fn source_id(&self) -> &str {
        "KALSHI"
    }

    async fn fetch_latest(&self, _since: Option<u64>) -> anyhow::Result<DataPayload> {
        // TODO: implement full Kalshi API ingestion
        // For now returns empty payload — no API key required but not yet implemented
        Ok(DataPayload {
            source_id: self.source_id().to_string(),
            timestamp: current_time_ms(),
            features: vec![],
            raw_count: 0,
        })
    }

    fn is_available(&self) -> bool {
        true
    }
}

use crate::checkpoint::{RegimeAssessment, SignalRecord};
use crate::config::ArgusConfig;
use crate::utils::current_time_ms;

pub struct SignalProducer;

impl SignalProducer {
    pub fn new() -> Self {
        Self
    }

    pub fn produce(
        &self,
        regime: &RegimeAssessment,
        _config: &ArgusConfig,
    ) -> Vec<SignalRecord> {
        let signals: Vec<(&str, &str, f64)> = match regime.regime_class.as_str() {
            "risk_on_growth" => vec![
                ("BTC-USDC", "long", 0.6),
                ("ETH-USDC", "long", 0.5),
                ("SOL-USDC", "long", 0.4),
            ],
            "risk_off_dollar_strength" => vec![
                ("BTC-USDC", "short", 0.5),
                ("ETH-USDC", "short", 0.4),
                ("SOL-USDC", "short", 0.3),
            ],
            "inflation_breakout" => vec![
                ("BTC-USDC", "long", 0.3),
                ("ETH-USDC", "neutral", 0.0),
            ],
            "deflation_risk" => vec![
                ("BTC-USDC", "short", 0.4),
                ("ETH-USDC", "short", 0.3),
            ],
            _ => vec![],
        };

        let now = current_time_ms();
        signals
            .into_iter()
            .map(|(market, direction, base_magnitude)| {
                let magnitude = base_magnitude * regime.confidence;
                let conviction = if regime.confidence > 0.75 {
                    "high"
                } else if regime.confidence > 0.5 {
                    "medium"
                } else {
                    "low"
                };
                SignalRecord {
                    id: uuid::Uuid::new_v4().to_string(),
                    market_id: market.to_string(),
                    direction: direction.to_string(),
                    magnitude,
                    conviction: conviction.to_string(),
                    expires_at: now + (regime.horizon_days as u64 * 86_400 * 1_000u64),
                    produced_at: now,
                    regime_source: regime.regime_class.clone(),
                    wal_sequence: 0,
                    published: false,
                }
            })
            .collect()
    }
}

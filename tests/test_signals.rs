use argus::checkpoint::RegimeAssessment;
use argus::config::ArgusConfig;
use argus::signals::SignalProducer;

fn regime(class: &str, confidence: f64) -> RegimeAssessment {
    RegimeAssessment {
        regime_class: class.to_string(),
        confidence,
        horizon_days: 3,
        produced_at: 1000,
        session_id: "s1".to_string(),
        model_version: "v1".to_string(),
        wal_sequence: 1,
    }
}

#[test]
fn test_risk_on_growth_produces_long_signals() {
    let producer = SignalProducer::new();
    let config = ArgusConfig::default();
    let signals = producer.produce(&regime("risk_on_growth", 1.0), &config);

    assert!(!signals.is_empty());
    for s in &signals {
        assert_eq!(s.direction, "long");
    }
    let markets: Vec<&str> = signals.iter().map(|s| s.market_id.as_str()).collect();
    assert!(markets.contains(&"BTC-USDC"));
    assert!(markets.contains(&"ETH-USDC"));
    assert!(markets.contains(&"SOL-USDC"));
}

#[test]
fn test_risk_off_produces_short_signals() {
    let producer = SignalProducer::new();
    let config = ArgusConfig::default();
    let signals = producer.produce(&regime("risk_off_dollar_strength", 0.8), &config);

    assert!(!signals.is_empty());
    for s in &signals {
        assert_eq!(s.direction, "short");
    }
}

#[test]
fn test_neutral_drift_produces_no_signals() {
    let producer = SignalProducer::new();
    let config = ArgusConfig::default();
    let signals = producer.produce(&regime("neutral_drift", 0.5), &config);
    assert!(signals.is_empty());
}

#[test]
fn test_magnitude_scaled_by_confidence() {
    let producer = SignalProducer::new();
    let config = ArgusConfig::default();

    let full = producer.produce(&regime("risk_on_growth", 1.0), &config);
    let half = producer.produce(&regime("risk_on_growth", 0.5), &config);

    let btc_full = full.iter().find(|s| s.market_id == "BTC-USDC").unwrap();
    let btc_half = half.iter().find(|s| s.market_id == "BTC-USDC").unwrap();

    assert!((btc_full.magnitude - btc_half.magnitude * 2.0).abs() < 1e-10);
}

#[test]
fn test_conviction_thresholds() {
    let producer = SignalProducer::new();
    let config = ArgusConfig::default();

    let high = producer.produce(&regime("risk_on_growth", 0.9), &config);
    assert_eq!(high[0].conviction, "high");

    let medium = producer.produce(&regime("risk_on_growth", 0.6), &config);
    assert_eq!(medium[0].conviction, "medium");

    let low = producer.produce(&regime("risk_on_growth", 0.3), &config);
    assert_eq!(low[0].conviction, "low");
}

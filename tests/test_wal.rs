use argus::wal::{
    ArgusWal, WalCheckpoint, WalDataIngested, WalInferenceCompleted, WalInferenceError,
    WalInferenceStarted, WalIngestError, WalSessionStart, WalSessionStop, WalSignalProduced,
    WalSignalPublished, CHECKPOINT, DATA_INGESTED, INFERENCE_COMPLETED, INFERENCE_ERROR,
    INFERENCE_STARTED, INGEST_ERROR, SESSION_START, SESSION_STOP, SIGNAL_PRODUCED,
    SIGNAL_PUBLISHED,
};
use std::collections::HashMap;
use tempfile::TempDir;

#[tokio::test]
async fn test_write_read_roundtrip_all_entry_types() {
    let dir = TempDir::new().unwrap();

    let wal = ArgusWal::open(dir.path()).await.unwrap();

    wal.append(DATA_INGESTED, &WalDataIngested {
        source: "KALSHI".into(),
        timestamp: 1000,
        feature_count: 5,
        feature_vector_hash: "abc".into(),
        ingest_duration_ms: 10,
    }).await.unwrap();

    wal.append(INFERENCE_STARTED, &WalInferenceStarted {
        session_id: "s1".into(),
        model_id: "m1".into(),
        model_version: "v1".into(),
        input_hash: "h1".into(),
        data_sources: vec!["KALSHI".into()],
        feature_count: 5,
    }).await.unwrap();

    wal.append(INFERENCE_COMPLETED, &WalInferenceCompleted {
        session_id: "s1".into(),
        model_id: "m1".into(),
        regime_class: "neutral_drift".into(),
        confidence: 0.5,
        reasoning_summary_hash: "rsh".into(),
        inference_duration_ms: 0,
    }).await.unwrap();

    wal.append(SIGNAL_PRODUCED, &WalSignalProduced {
        market_id: "BTC-USDC".into(),
        direction: "long".into(),
        magnitude: 0.3,
        conviction: "low".into(),
        horizon_days: 3,
        expires_at: 9999999,
        regime_source: "neutral_drift".into(),
    }).await.unwrap();

    wal.append(SIGNAL_PUBLISHED, &WalSignalPublished {
        signal_ids: vec!["id1".into()],
        published_to: "stdout".into(),
        ack_received: true,
        wal_sequence: 4,
    }).await.unwrap();

    wal.append(CHECKPOINT, &WalCheckpoint {
        session_id: "s1".into(),
        last_processed: HashMap::new(),
        regime_history_count: 1,
        signals_produced_count: 1,
        model_version: "v1".into(),
    }).await.unwrap();

    wal.append(SESSION_START, &WalSessionStart {
        session_id: "s1".into(),
        argus_version: "0.1.0".into(),
        model_configs: vec!["argus-placeholder".into()],
        data_sources: vec!["KALSHI".into()],
        reason: "fresh".into(),
    }).await.unwrap();

    wal.append(SESSION_STOP, &WalSessionStop {
        session_id: "s1".into(),
        reason: "clean".into(),
        final_sequence: 7,
        signals_produced: 1,
    }).await.unwrap();

    wal.append(INGEST_ERROR, &WalIngestError {
        source: "FRED".into(),
        error: "no api key".into(),
        will_retry: false,
    }).await.unwrap();

    wal.append(INFERENCE_ERROR, &WalInferenceError {
        model_id: "m1".into(),
        error: "timeout".into(),
        input_hash: "h1".into(),
    }).await.unwrap();

    let seg = dir.path().join("argus_wal_0000.log");
    let entries = ArgusWal::read_from(&seg, 0).unwrap();
    assert_eq!(entries.len(), 10);

    assert_eq!(entries[0].entry_type, DATA_INGESTED);
    assert_eq!(entries[1].entry_type, INFERENCE_STARTED);
    assert_eq!(entries[2].entry_type, INFERENCE_COMPLETED);
    assert_eq!(entries[3].entry_type, SIGNAL_PRODUCED);
    assert_eq!(entries[4].entry_type, SIGNAL_PUBLISHED);
    assert_eq!(entries[5].entry_type, CHECKPOINT);
    assert_eq!(entries[6].entry_type, SESSION_START);
    assert_eq!(entries[7].entry_type, SESSION_STOP);
    assert_eq!(entries[8].entry_type, INGEST_ERROR);
    assert_eq!(entries[9].entry_type, INFERENCE_ERROR);
}

#[tokio::test]
async fn test_crc_corruption_detected() {
    let dir = TempDir::new().unwrap();
    let wal = ArgusWal::open(dir.path()).await.unwrap();
    wal.append(DATA_INGESTED, &WalDataIngested {
        source: "KALSHI".into(),
        timestamp: 1,
        feature_count: 0,
        feature_vector_hash: "x".into(),
        ingest_duration_ms: 0,
    }).await.unwrap();
    drop(wal);

    let seg = dir.path().join("argus_wal_0000.log");
    let mut data = std::fs::read(&seg).unwrap();
    // Corrupt a byte in the payload area
    let last = data.len() - 1;
    data[last] ^= 0xFF;
    std::fs::write(&seg, data).unwrap();

    let result = ArgusWal::read_from(&seg, 0);
    assert!(result.is_err(), "expected CRC error");
}

#[tokio::test]
async fn test_after_seq_filter() {
    let dir = TempDir::new().unwrap();
    let wal = ArgusWal::open(dir.path()).await.unwrap();
    for i in 0..5u64 {
        wal.append(DATA_INGESTED, &WalDataIngested {
            source: "KALSHI".into(),
            timestamp: i,
            feature_count: 0,
            feature_vector_hash: "x".into(),
            ingest_duration_ms: 0,
        }).await.unwrap();
    }
    drop(wal);

    let seg = dir.path().join("argus_wal_0000.log");
    let entries = ArgusWal::read_from(&seg, 3).unwrap();
    assert_eq!(entries.len(), 2);
    assert_eq!(entries[0].sequence, 4);
    assert_eq!(entries[1].sequence, 5);
}

#[tokio::test]
async fn test_find_last_checkpoint() {
    let dir = TempDir::new().unwrap();
    let wal = ArgusWal::open(dir.path()).await.unwrap();

    wal.append(DATA_INGESTED, &WalDataIngested {
        source: "KALSHI".into(),
        timestamp: 1,
        feature_count: 0,
        feature_vector_hash: "x".into(),
        ingest_duration_ms: 0,
    }).await.unwrap();

    wal.append(CHECKPOINT, &WalCheckpoint {
        session_id: "s1".into(),
        last_processed: HashMap::new(),
        regime_history_count: 0,
        signals_produced_count: 0,
        model_version: "v1".into(),
    }).await.unwrap();

    wal.append(CHECKPOINT, &WalCheckpoint {
        session_id: "s1".into(),
        last_processed: HashMap::new(),
        regime_history_count: 5,
        signals_produced_count: 3,
        model_version: "v2".into(),
    }).await.unwrap();

    drop(wal);

    let result = ArgusWal::find_last_checkpoint(dir.path()).await.unwrap();
    assert!(result.is_some());
    let (seq, cp) = result.unwrap();
    assert_eq!(cp.regime_history_count, 5);
    assert_eq!(cp.model_version, "v2");
    assert_eq!(seq, 3);
}

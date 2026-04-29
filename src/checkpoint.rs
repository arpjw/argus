use std::collections::{HashMap, VecDeque};

use serde::{Deserialize, Serialize};

use crate::utils::current_time_ms;

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct RegimeAssessment {
    pub regime_class: String,
    pub confidence: f64,
    pub horizon_days: u32,
    pub produced_at: u64,
    pub session_id: String,
    pub model_version: String,
    pub wal_sequence: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct SignalRecord {
    pub id: String,
    pub market_id: String,
    pub direction: String,
    pub magnitude: f64,
    pub conviction: String,
    pub expires_at: u64,
    pub produced_at: u64,
    pub regime_source: String,
    pub wal_sequence: u64,
    pub published: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct ArgusCheckpoint {
    pub session_id: String,
    pub last_processed: HashMap<String, u64>,
    pub regime_history: VecDeque<RegimeAssessment>,
    pub active_signals: HashMap<String, SignalRecord>,
    pub model_versions: HashMap<String, String>,
    pub created_at: u64,
    pub signals_produced_total: u64,
    pub inferences_run_total: u64,
}

impl ArgusCheckpoint {
    pub fn new(session_id: String) -> Self {
        Self {
            session_id,
            created_at: current_time_ms(),
            ..Default::default()
        }
    }

    pub fn apply_regime_assessment(&mut self, assessment: RegimeAssessment) {
        self.regime_history.push_back(assessment);
        if self.regime_history.len() > 10 {
            self.regime_history.pop_front();
        }
        self.inferences_run_total += 1;
    }

    pub fn apply_signal_produced(&mut self, signal: SignalRecord) {
        self.active_signals.insert(signal.id.clone(), signal);
        self.signals_produced_total += 1;
    }

    pub fn purge_expired_signals(&mut self) {
        let now = current_time_ms();
        self.active_signals.retain(|_, s| s.expires_at > now);
    }

    pub fn latest_regime(&self) -> Option<&RegimeAssessment> {
        self.regime_history.back()
    }
}

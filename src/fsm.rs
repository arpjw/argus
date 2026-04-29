use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::wal::ArgusWal;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum ArgusState {
    Idle,
    IngestingData,
    RunningClassifier,
    RunningGenerative,
    ProducingSignals,
    PublishingSignals,
    WaitingForNextTick,
    Recovering,
    Paused,
    Stopping,
}

#[derive(Debug, Clone)]
pub enum ArgusEvent {
    Start,
    DataIngested { source: String },
    AllSourcesIngested,
    ClassificationComplete { regime: String, confidence: f64 },
    GenerativeComplete,
    SignalsProduced { count: usize },
    SignalsPublished,
    TickElapsed,
    IngestError { source: String, error: String },
    InferenceError { model: String, error: String },
    Pause,
    Resume,
    Stop,
}

pub struct ArgusFsm {
    pub state: ArgusState,
    pub wal: Arc<ArgusWal>,
    pub session_id: String,
}

impl ArgusFsm {
    pub fn new(wal: Arc<ArgusWal>, session_id: String) -> Self {
        Self {
            state: ArgusState::Idle,
            wal,
            session_id,
        }
    }

    pub async fn transition(&mut self, event: ArgusEvent) -> anyhow::Result<ArgusState> {
        let new_state = match (&self.state, &event) {
            (ArgusState::Idle, ArgusEvent::Start) => ArgusState::IngestingData,

            (ArgusState::IngestingData, ArgusEvent::AllSourcesIngested) => {
                ArgusState::RunningClassifier
            }

            (ArgusState::IngestingData, ArgusEvent::IngestError { .. }) => {
                ArgusState::IngestingData
            }

            (ArgusState::RunningClassifier, ArgusEvent::ClassificationComplete { .. }) => {
                ArgusState::RunningGenerative
            }

            (ArgusState::RunningGenerative, ArgusEvent::GenerativeComplete) => {
                ArgusState::ProducingSignals
            }

            (ArgusState::ProducingSignals, ArgusEvent::SignalsProduced { .. }) => {
                ArgusState::PublishingSignals
            }

            (ArgusState::PublishingSignals, ArgusEvent::SignalsPublished) => {
                ArgusState::WaitingForNextTick
            }

            (ArgusState::WaitingForNextTick, ArgusEvent::TickElapsed) => {
                ArgusState::IngestingData
            }

            (ArgusState::RunningClassifier, ArgusEvent::InferenceError { .. }) => {
                ArgusState::ProducingSignals
            }

            (_, ArgusEvent::Pause) => ArgusState::Paused,
            (ArgusState::Paused, ArgusEvent::Resume) => ArgusState::Idle,
            (_, ArgusEvent::Stop) => ArgusState::Stopping,

            _ => self.state.clone(),
        };

        self.state = new_state.clone();
        Ok(new_state)
    }
}

use std::path::PathBuf;
use std::sync::Arc;

use clap::Parser;
use tokio::sync::Mutex;

mod checkpoint;
mod config;
mod fsm;
mod ingest;
mod inference;
mod publish;
mod session;
mod signals;
mod utils;
mod wal;

use config::ArgusConfig;
use session::ArgusSession;
use wal::ArgusWal;

#[derive(Parser)]
#[command(name = "argus")]
#[command(about = "Monolith Systematic — macro intelligence engine")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(clap::Subcommand)]
enum Commands {
    Run {
        #[arg(long, default_value = "~/.argus/config.json")]
        config: PathBuf,
    },
    Status {
        #[arg(long, default_value = "~/.argus/sessions/default")]
        session_dir: PathBuf,
    },
    Signals {
        #[arg(long, default_value = "~/.argus/sessions/default")]
        session_dir: PathBuf,
    },
    WalDump {
        #[arg(long)]
        path: PathBuf,
        #[arg(long, default_value = "50")]
        limit: usize,
    },
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter("argus=info")
        .init();

    let cli = Cli::parse();

    match cli.command {
        Commands::Run { config } => {
            let config = if config.exists() {
                ArgusConfig::from_file(&config)?
            } else {
                ArgusConfig::default()
            };

            let session = ArgusSession::new(config).await?;
            let session_ref = Arc::new(Mutex::new(session));
            let session_clone = session_ref.clone();

            tokio::select! {
                result = async move { session_clone.lock().await.run().await } => result?,
                _ = tokio::signal::ctrl_c() => {
                    tracing::info!("Received Ctrl+C, shutting down cleanly...");
                    session_ref.lock().await
                        .fsm.transition(crate::fsm::ArgusEvent::Stop).await?;
                }
            }
        }

        Commands::Status { session_dir } => {
            let session_dir = expand_tilde(session_dir);
            if let Some((_seq, cp)) = ArgusWal::find_last_checkpoint(&session_dir).await? {
                println!("Session:           {}", cp.session_id);
                println!("Regimes assessed:  {}", cp.regime_history_count);
                println!("Signals produced:  {}", cp.signals_produced_count);
                println!("Model version:     {}", cp.model_version);
            } else {
                println!("No session found at {:?}", session_dir);
            }
        }

        Commands::Signals { session_dir } => {
            let session_dir = expand_tilde(session_dir);
            let cp_path = session_dir.join("checkpoint.json");
            if cp_path.exists() {
                let data = std::fs::read_to_string(&cp_path)?;
                let cp: checkpoint::ArgusCheckpoint = serde_json::from_str(&data)?;
                let signals: Vec<&checkpoint::SignalRecord> =
                    cp.active_signals.values().collect();
                println!("{}", serde_json::to_string_pretty(&signals)?);
            } else {
                println!("No checkpoint found at {:?}", cp_path);
            }
        }

        Commands::WalDump { path, limit } => {
            let entries = ArgusWal::read_from(&path, 0)?;
            for entry in entries.iter().take(limit) {
                println!(
                    "seq={} type={} ts={}",
                    entry.sequence, entry.entry_type, entry.timestamp_ns
                );
            }
        }
    }

    Ok(())
}

fn expand_tilde(path: PathBuf) -> PathBuf {
    let s = path.to_string_lossy();
    if s.starts_with("~/") {
        if let Some(home) = dirs::home_dir() {
            return home.join(&s[2..]);
        }
    }
    path
}

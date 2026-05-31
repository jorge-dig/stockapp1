"""
Daily scheduled jobs using APScheduler.
Run as: python -m app.scheduler.jobs
"""
import logging
import os
from datetime import date

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Configurable via env. Default: 18:05 local time (after NYSE close at 16:00 ET)
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "18"))
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "5"))
SCHEDULE_TZ = os.getenv("SCHEDULE_TZ", "America/New_York")


def job_update_data():
    logger.info("=== JOB: update_data ===")
    from app.data.history import incremental_update
    try:
        incremental_update()
    except Exception as e:
        logger.error(f"job_update_data failed: {e}")


def job_calc_indicators():
    logger.info("=== JOB: calc_indicators ===")
    from app.indicators.calculator import calc_all_tickers
    from datetime import timedelta
    try:
        calc_all_tickers(since=date.today() - timedelta(days=3))
    except Exception as e:
        logger.error(f"job_calc_indicators failed: {e}")


def job_run_strategies():
    logger.info("=== JOB: run_strategies ===")
    from app.strategies.engine import run_all_strategies
    try:
        run_all_strategies()
    except Exception as e:
        logger.error(f"job_run_strategies failed: {e}")


def job_send_alerts():
    logger.info("=== JOB: send_alerts ===")
    from app.alerts.writer import write_signals, dispatch_alerts
    try:
        write_signals()
        dispatch_alerts()
    except Exception as e:
        logger.error(f"job_send_alerts failed: {e}")


def job_generate_report():
    logger.info("=== JOB: generate_report ===")
    from app.reports.generator import generate_daily_report
    try:
        generate_daily_report()
    except Exception as e:
        logger.error(f"job_generate_report failed: {e}")


def run_daily_pipeline():
    """Run full daily pipeline manually (for testing or backfill)."""
    job_update_data()
    job_calc_indicators()
    job_run_strategies()
    job_send_alerts()
    job_generate_report()


def start_scheduler():
    scheduler = BlockingScheduler(timezone=SCHEDULE_TZ)

    # Chain jobs sequentially with 5-minute gaps
    scheduler.add_job(job_update_data,     CronTrigger(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE,     timezone=SCHEDULE_TZ), id="update_data")
    scheduler.add_job(job_calc_indicators, CronTrigger(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE+5,  timezone=SCHEDULE_TZ), id="calc_indicators")
    scheduler.add_job(job_run_strategies,  CronTrigger(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE+15, timezone=SCHEDULE_TZ), id="run_strategies")
    scheduler.add_job(job_send_alerts,     CronTrigger(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE+20, timezone=SCHEDULE_TZ), id="send_alerts")
    scheduler.add_job(job_generate_report, CronTrigger(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE+25, timezone=SCHEDULE_TZ), id="generate_report")

    logger.info(
        f"Scheduler started. Daily pipeline at {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} {SCHEDULE_TZ}. "
        "Press Ctrl+C to exit."
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-now", action="store_true", help="Run the full pipeline immediately then exit")
    args = parser.parse_args()

    if args.run_now:
        run_daily_pipeline()
    else:
        start_scheduler()

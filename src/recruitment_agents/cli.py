from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from recruitment_agents.workflow import build_workflow, draw_mermaid


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    job_description = Path(args.job).read_text(encoding="utf-8")
    resume_paths = [str(Path(path)) for path in args.resumes]
    outbox_dir = str(Path(args.outbox or root / "data" / "outbox"))
    checkpoint_db = str(Path(args.checkpoint_db or root / "data" / "checkpoints.sqlite"))

    workflow = build_workflow(checkpoint_path=checkpoint_db)
    config = {"configurable": {"thread_id": args.thread_id}}
    if args.resume_approval:
        result = resume_approval(workflow, args, config)
    else:
        result = workflow.invoke(
            {
                "job_description": job_description,
                "resume_paths": resume_paths,
                "threshold": args.threshold,
                "timezone": args.timezone,
                "outbox_dir": outbox_dir,
                "approval_status": "approved" if args.approve else args.approval_status,
                "approval_file": args.approval_file or "",
                "approved_by": args.approved_by,
                "approval_notes": args.approval_notes,
            },
            config=config,
        )

    print("=== LangGraph 招聘工作流 ===")
    print(draw_mermaid())
    interrupts = extract_interrupts(result)
    if interrupts:
        print("=== Workflow paused for HR approval ===")
        print(json.dumps(to_jsonable(interrupts), ensure_ascii=False, indent=2))
        print(f"Resume with: --thread-id {args.thread_id} --resume-approval approved")
        return
    print("=== 候选人排名 ===")
    for index, match in enumerate(result.get("candidate_matches", []), start=1):
        print(
            f"{index}. {match.candidate.name} | {match.recommendation} | "
            f"{match.score.weighted_total} | 缺口: {', '.join(match.score.missing_skills) or '无'}"
        )
    print("=== 事件 ===")
    for event in result.get("events", []):
        print(f"[{event.node}] {event.message}")
    print("=== 通知投递 ===")
    approval = result.get("approval_decision")
    if approval:
        print(f"HR approval = {approval.status}")
    delivery_results = result.get("delivery_results", [])
    stats: dict[str, int] = {}
    for item in delivery_results:
        key = f"{item.channel}:{item.status}"
        stats[key] = stats.get(key, 0) + 1
    for key, count in sorted(stats.items()):
        print(f"{key} = {count}")
    print(f"=== 邮件草稿已写入: {outbox_dir} ===")

    if args.json:
        print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-agent recruiting workflow demo.")
    parser.add_argument("--job", default="data/sample_job.txt", help="Path to job description text file.")
    parser.add_argument(
        "--resumes",
        nargs="+",
        default=["data/resumes"],
        help="Resume files or directories. Supports txt/md/pdf/docx/images when optional deps are installed.",
    )
    parser.add_argument("--threshold", type=float, default=70, help="Shortlist score threshold.")
    parser.add_argument("--timezone", default="Asia/Shanghai", help="IANA timezone for interview scheduling.")
    parser.add_argument("--outbox", default=None, help="Directory for generated email JSON drafts.")
    parser.add_argument(
        "--approval-status",
        choices=["pending", "approved", "rejected"],
        default="pending",
        help="Manual HR approval status for candidate-facing sends.",
    )
    parser.add_argument("--approve", action="store_true", help="Approve candidate-facing notifications for this run.")
    parser.add_argument("--approval-file", default="", help="JSON file containing status/approved_by/notes.")
    parser.add_argument("--approved-by", default="HR reviewer", help="Name recorded when approval is granted.")
    parser.add_argument("--approval-notes", default="", help="Approval notes recorded in workflow state.")
    parser.add_argument("--thread-id", default="recruitment-demo", help="LangGraph checkpoint thread ID.")
    parser.add_argument("--checkpoint-db", default="", help="SQLite checkpoint DB path.")
    parser.add_argument(
        "--resume-approval",
        choices=["approved", "rejected"],
        default="",
        help="Resume a paused checkpointed workflow with an HR decision.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON state.")
    return parser.parse_args()


def resume_approval(workflow: Any, args: argparse.Namespace, config: dict[str, Any]) -> Any:
    try:
        from langgraph.types import Command
    except ImportError as exc:
        raise RuntimeError("Resuming approval checkpoints requires langgraph to be installed.") from exc

    return workflow.invoke(
        Command(
            resume={
                "status": args.resume_approval,
                "approved_by": args.approved_by,
                "notes": args.approval_notes,
            }
        ),
        config=config,
    )


def extract_interrupts(result: Any) -> Any:
    interrupts = getattr(result, "interrupts", None)
    if interrupts:
        return interrupts
    if isinstance(result, dict):
        return result.get("__interrupt__")
    return None


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return to_jsonable(value.value)
    return value


if __name__ == "__main__":
    main()

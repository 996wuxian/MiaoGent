import argparse
from collections.abc import Sequence

from qq_mail_agent_cli.agent import MailAgent
from qq_mail_agent_cli.config import load_app_config, load_deepseek_config, load_mail_config
from qq_mail_agent_cli.llm_client import DeepSeekClient
from qq_mail_agent_cli.mail_client import MailClient
from qq_mail_agent_cli.services import DraftService, DraftServiceError
from qq_mail_agent_cli.storage import StateStore, StoredDraft


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qq-mail-agent",
        description="Safe-first QQ Mail AI agent CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List recent mock emails.")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--real", action="store_true", help="Read from QQ Mail IMAP instead of mock emails.")
    list_parser.add_argument("--snippet", action="store_true", help="Show truncated body snippets for real emails.")

    triage_parser = subparsers.add_parser("triage", help="Classify recent mock emails.")
    triage_parser.add_argument("--limit", type=int, default=20)
    triage_parser.add_argument("--ai", action="store_true", help="Use DeepSeek instead of local mock rules.")
    triage_parser.add_argument("--real", action="store_true", help="Read from QQ Mail IMAP instead of mock emails.")

    draft_parser = subparsers.add_parser("draft", help="Generate a mock reply draft.")
    draft_parser.add_argument("--id", required=True, dest="mail_id")
    draft_parser.add_argument("--ai", action="store_true", help="Use DeepSeek instead of local mock draft.")
    draft_parser.add_argument("--real", action="store_true", help="Read the source email from QQ Mail IMAP.")

    translate_parser = subparsers.add_parser("translate", help="Translate an email into Simplified Chinese.")
    translate_parser.add_argument("--id", required=True, dest="mail_id")
    translate_parser.add_argument("--ai", action="store_true", help="Use DeepSeek instead of local mock translation.")
    translate_parser.add_argument("--real", action="store_true", help="Read the source email from QQ Mail IMAP.")

    send_parser = subparsers.add_parser("send", help="Send a draft. Defaults to dry-run.")
    send_parser.add_argument("--draft", required=True, dest="draft_id")
    send_parser.add_argument("--yes-send", action="store_true", help="Attempt real SMTP send instead of dry-run.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = load_mail_config()
    client = MailClient(config)
    agent = _build_agent(use_ai=getattr(args, "ai", False))

    if args.command == "list":
        for message in _list_messages(client, real=args.real, limit=args.limit):
            if args.real:
                fields = [message.id, _seen_label(message), message.sender, message.subject, message.date or ""]
                if args.snippet:
                    fields.append(message.snippet)
                print("\t".join(fields))
            else:
                print(f"{message.id}\t{message.sender}\t{message.subject}")
        return 0

    if args.command == "triage":
        for message in _list_messages(client, real=args.real, limit=args.limit):
            result = agent.triage(message)
            print(
                f"{message.id}\t{result.classification.value}\t"
                f"{result.suggested_action.value}\t{result.reason}\t{result.action_reason}"
            )
        return 0

    if args.command == "draft":
        message = _get_message(client, mail_id=args.mail_id, real=args.real)
        if message is None:
            parser.error(f"Unknown mail id: {args.mail_id}")
        draft = agent.draft_reply(message)
        print(f"Draft: {draft.id}")
        print(f"To: {draft.to}")
        print(f"Subject: {draft.subject}")
        print()
        print(draft.body)
        return 0

    if args.command == "translate":
        message = _get_message(client, mail_id=args.mail_id, real=args.real)
        if message is None:
            parser.error(f"Unknown mail id: {args.mail_id}")
        translation = agent.translate_message(message)
        print(f"Translation: {translation.mail_id}")
        print(f"Subject: {translation.subject_zh}")
        print()
        print(translation.body_zh)
        return 0

    if args.command == "send":
        dry_run = not args.yes_send
        service = DraftService(client, StateStore(load_app_config().db_path))
        try:
            stored = service.get_sendable_draft(args.draft_id)
            _print_stored_draft(stored)
            print(service.send_stored_draft(args.draft_id, dry_run=dry_run, source="CLI"))
        except DraftServiceError as error:
            parser.error(str(error))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _print_stored_draft(draft: StoredDraft) -> None:
    print(f"Draft: {draft.draft_id}")
    print(f"Status: {draft.send_status}")
    print(f"To: {draft.to_addr}")
    print(f"Subject: {draft.subject}")
    print()
    print(draft.body)
    print()


def _list_messages(client: MailClient, *, real: bool, limit: int):
    if real:
        return client.list_real_recent(limit)
    return client.list_recent(limit)


def _get_message(client: MailClient, *, mail_id: str, real: bool):
    if real:
        return client.get_real_message(mail_id)
    messages = {message.id: message for message in client.list_recent(100)}
    return messages.get(mail_id)


def _build_agent(*, use_ai: bool) -> MailAgent:
    if not use_ai:
        return MailAgent()
    return MailAgent(llm_client=DeepSeekClient(load_deepseek_config()))


def _seen_label(message) -> str:
    if message.is_seen is True:
        return "seen"
    if message.is_seen is False:
        return "unread"
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())

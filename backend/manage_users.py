"""Manage local application users from the server console."""
from __future__ import annotations

import argparse
import getpass

from auth import MIN_PASSWORD_LENGTH, hash_password, validate_username
from repository import UsernameTaken, create_repository


def _validated_username(value: str) -> str:
    try:
        return validate_username(value)
    except ValueError as exc:
        raise SystemExit(
            "用户名必须为 2-64 位，可使用中英文、大小写字母、数字、空格和常用符号。"
        ) from exc


def _prompt_password() -> str:
    password = getpass.getpass(f"密码（至少 {MIN_PASSWORD_LENGTH} 位）：")
    confirmation = getpass.getpass("再次输入密码：")
    if password != confirmation:
        raise SystemExit("两次输入的密码不一致。")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"密码必须至少 {MIN_PASSWORD_LENGTH} 位。")
    return password


def create_user(username: str) -> None:
    repository = create_repository()
    try:
        user = repository.create_password_user(
            _validated_username(username),
            hash_password(_prompt_password()),
        )
    except UsernameTaken as exc:
        raise SystemExit("用户名已存在。") from exc
    print(f"已创建用户：{user['username']}")


def reset_password(username: str) -> None:
    repository = create_repository()
    if not repository.set_password(
        _validated_username(username),
        hash_password(_prompt_password()),
    ):
        raise SystemExit("用户不存在。")
    print(f"已重置用户密码：{username.strip()}")


def list_users() -> None:
    repository = create_repository()
    users = repository.list_users()
    if not users:
        print("暂无用户。")
        return
    for user in users:
        status = "启用" if user["is_active"] else "停用"
        print(f"{user['username']}\t{status}\t{user['id']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="管理本地登录账号")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="创建用户")
    create_parser.add_argument("username")

    reset_parser = subparsers.add_parser("reset-password", help="重置用户密码")
    reset_parser.add_argument("username")

    subparsers.add_parser("list", help="列出用户")
    args = parser.parse_args()

    if args.command == "create":
        create_user(args.username)
    elif args.command == "reset-password":
        reset_password(args.username)
    else:
        list_users()


if __name__ == "__main__":
    main()

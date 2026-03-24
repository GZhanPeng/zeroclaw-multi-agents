#!/usr/bin/env bash
set -e

ROLE="$1"

BASE_DIR="workspace"
ROLE_DIR="$BASE_DIR/character/$ROLE"

if [[ -z "$ROLE" ]]; then
  echo "[ERR] 用法: ./switch_role.sh <role_name>"
  exit 1
fi

if [[ ! -d "$ROLE_DIR" ]]; then
  echo "[ERR] 角色不存在: $ROLE"
  exit 1
fi

echo "[INFO] 切换角色 → $ROLE"

# 覆盖 SOUL
if [[ -f "$ROLE_DIR/SOUL.md" ]]; then
  cp "$ROLE_DIR/SOUL.md" "$BASE_DIR/SOUL.md"
  echo "  ✓ SOUL.md 已切换"
else
  echo "  ⚠ 缺少 SOUL.md"
fi

# 覆盖 IDENTITY
if [[ -f "$ROLE_DIR/IDENTITY.md" ]]; then
  cp "$ROLE_DIR/IDENTITY.md" "$BASE_DIR/IDENTITY.md"
  echo "  ✓ IDENTITY.md 已切换"
else
  echo "  ⚠ 缺少 IDENTITY.md"
fi

echo "[DONE]"
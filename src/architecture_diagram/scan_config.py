"""AST 扫描器的默认排除规则；版本变更会标记 facts 失效。"""

EXCLUSION_RULES_VERSION = "scan-exclusions-v2"

# Keep the optimized scanner explicit until its compatibility behavior is intentionally changed.
LEGACY_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    "site-packages", "node_modules", "build", "dist", "tests", "test",
    "evaluation", "eval", "benchmarks", "benchmark", "scripts",
}

# 保留现有测试/评测/脚本排除边界，并显式跳过生成物、缓存和基线快照。
DEFAULT_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "virtualenv", "__pycache__",
    "site-packages", "node_modules", "build", "dist", "outputs", "baseline", ".cache",
    "tests", "test", "evaluation", "eval", "benchmarks", "benchmark", "scripts",
}

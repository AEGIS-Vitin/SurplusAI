#!/usr/bin/env bash
set -euo pipefail

# Pre-deployment validation for SurplusAI / AEGIS-FOOD
# Ensures everything is ready before deploying to Railway/Fly.io/VPS

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

pass()  { echo -e "  ${GREEN}[PASS]${NC} $1"; }
fail()  { echo -e "  ${RED}[FAIL]${NC} $1"; ((ERRORS++)); }
warn()  { echo -e "  ${YELLOW}[WARN]${NC} $1"; ((WARNINGS++)); }

echo ""
echo "══════════════════════════════════════════"
echo "  SurplusAI Pre-Deploy Check"
echo "  $(date '+%Y-%m-%d %H:%M')"
echo "══════════════════════════════════════════"
echo ""

cd "$(dirname "$0")/.."

# 1. Required files
echo "── Files ──"
for f in Dockerfile.prod railway.toml fly.toml deploy.sh backend/requirements.txt backend/main.py; do
    [ -f "$f" ] && pass "$f exists" || fail "$f missing"
done

# 2. Python syntax
echo ""
echo "── Python Syntax ──"
PY_ERRORS=0
for f in $(find backend -name "*.py" 2>/dev/null); do
    python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null || { fail "Syntax error: $f"; ((PY_ERRORS++)); }
done
[ "$PY_ERRORS" -eq 0 ] && pass "All Python files valid"

# 3. Requirements
echo ""
echo "── Dependencies ──"
if [ -f backend/requirements.txt ]; then
    REQ_COUNT=$(wc -l < backend/requirements.txt | tr -d ' ')
    pass "requirements.txt: $REQ_COUNT dependencies"

    for pkg in fastapi uvicorn sqlalchemy asyncpg; do
        grep -qi "$pkg" backend/requirements.txt && pass "  $pkg found" || warn "  $pkg not in requirements.txt"
    done
else
    fail "requirements.txt not found"
fi

# 4. Dockerfile validation
echo ""
echo "── Dockerfile.prod ──"
grep -q "HEALTHCHECK" Dockerfile.prod && pass "Health check defined" || warn "No HEALTHCHECK in Dockerfile"
grep -q "USER" Dockerfile.prod && pass "Non-root user configured" || warn "Running as root"
grep -q "EXPOSE" Dockerfile.prod && pass "Port exposed" || warn "No EXPOSE directive"

# 5. Environment vars template
echo ""
echo "── Environment ──"
if [ -f .env.prod.example ] || [ -f .env.example ]; then
    pass "Environment template exists"
else
    warn "No .env.prod.example — create one for deploy documentation"
fi

# 6. Docker build test (dry run)
echo ""
echo "── Docker Build (dry run) ──"
if command -v docker &>/dev/null; then
    if docker build --check -f Dockerfile.prod . 2>/dev/null; then
        pass "Dockerfile.prod syntax valid"
    else
        # --check not available in all versions, try parse
        docker build -f Dockerfile.prod --no-cache --progress=plain . -t surplusai-test 2>&1 | head -5 >/dev/null 2>&1 && \
            pass "Docker build starts OK" || warn "Docker build may have issues (run manually to verify)"
    fi
else
    warn "Docker not available for build test"
fi

# 7. Tests
echo ""
echo "── Tests ──"
if [ -d backend/tests ] || [ -d tests ]; then
    TEST_COUNT=$(find . -name "test_*.py" -o -name "*_test.py" | wc -l | tr -d ' ')
    pass "Test files found: $TEST_COUNT"
else
    warn "No test directory found"
fi

# 8. Security checks
echo ""
echo "── Security ──"
# Check for hardcoded secrets
SECRETS_FOUND=0
for pattern in "password=" "secret_key=" "api_key=" "token="; do
    MATCHES=$(grep -rni "$pattern" backend/ --include="*.py" 2>/dev/null | grep -v "os.environ\|os.getenv\|settings\.\|config\.\|#\|test\|example\|placeholder" | head -3)
    if [ -n "$MATCHES" ]; then
        warn "Potential hardcoded secret ($pattern)"
        ((SECRETS_FOUND++))
    fi
done
[ "$SECRETS_FOUND" -eq 0 ] && pass "No hardcoded secrets detected"

# Check .gitignore
if [ -f .gitignore ]; then
    grep -q ".env" .gitignore && pass ".env in .gitignore" || warn ".env not in .gitignore"
else
    warn "No .gitignore file"
fi

# 9. Summary
echo ""
echo "══════════════════════════════════════════"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "  ${GREEN}✅ READY TO DEPLOY${NC} ($WARNINGS warnings)"
    echo "  Deploy with: ./deploy.sh railway"
    echo "  Or:          ./deploy.sh fly"
else
    echo -e "  ${RED}❌ NOT READY ($ERRORS errors, $WARNINGS warnings)${NC}"
    echo "  Fix errors above before deploying."
fi
echo "══════════════════════════════════════════"
echo ""

exit $ERRORS

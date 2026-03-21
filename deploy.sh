#!/bin/bash
# Claude Code 터미널에서 실행할 배포 스크립트
# 사용법: bash deploy.sh

echo "🚀 AI 전자책 메이커 v2 배포 시작"

# 1. GitHub repo 확인
read -p "GitHub repo URL (예: https://github.com/doyaclass-spec/ebook-ai): " REPO_URL

if [ -z "$REPO_URL" ]; then
  echo "❌ repo URL을 입력해주세요"
  exit 1
fi

# 2. 기존 repo clone 또는 초기화
REPO_NAME=$(basename $REPO_URL .git)

if [ -d "$REPO_NAME" ]; then
  echo "📁 기존 폴더 발견, 파일 복사 중..."
  cp app.py $REPO_NAME/
  cp templates/index.html $REPO_NAME/templates/
  cp requirements.txt $REPO_NAME/
  cp Procfile $REPO_NAME/
  cd $REPO_NAME
else
  echo "📁 새 폴더 생성 중..."
  git init $REPO_NAME
  cp -r . $REPO_NAME/
  cd $REPO_NAME
  git remote add origin $REPO_URL
fi

# 3. .gitignore
cat > .gitignore << 'EOF'
__pycache__/
*.pyc
.env
*.pdf
*.epub
venv/
.DS_Store
EOF

# 4. Git push
git add -A
git commit -m "feat: ebook-ai v2 (차트+인포그래픽+이미지+편집기+EPUB)"
git push -u origin main

echo ""
echo "✅ GitHub 푸시 완료!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Render 설정 (render.com)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Build Command:"
echo "  apt-get update && apt-get install -y fonts-noto-cjk && pip install -r requirements.txt"
echo ""
echo "Start Command:"
echo "  gunicorn app:app --bind 0.0.0.0:\$PORT --workers 2 --timeout 120"
echo ""
echo "환경변수 (Render → Environment 탭):"
echo "  ANTHROPIC_API_KEY = sk-ant-..."
echo "  GEMINI_API_KEY    = AIza..."
echo "  SUPABASE_URL      = https://xxx.supabase.co"
echo "  SUPABASE_KEY      = eyJ..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Supabase 설정"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  supabase.com → 프로젝트 → SQL Editor"
echo "  supabase_schema.sql 내용 붙여넣고 실행"
echo ""

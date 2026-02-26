#!/bin/bash
# Buduje PEŁNY deployment package (kod + deps) dla Lambda
# Uruchom: ./build_full.zip.sh [amd64|arm64]
# Domyślnie: obie architektury (lambda_full_x86.zip + lambda_full_arm.zip)

set -e
cd "$(dirname "$0")"

ARCH="${1:-both}"

build_for() {
  local plat=$1
  local suffix=$2
  local BUILD_DIR="lambda_build_$suffix"
  rm -rf "$BUILD_DIR"
  mkdir -p "$BUILD_DIR"

  echo "=== Budowanie dla $plat ==="
  echo "1. Kopiowanie kodu..."
  cp lambda_handler.py db.py "$BUILD_DIR/"
  cp -r tools "$BUILD_DIR/"

  echo "2. Instalowanie pakietów (Linux $plat)..."
  docker run --platform "$plat" --rm --entrypoint "" \
    -v "$(pwd)/$BUILD_DIR:/var/task" \
    -w /var/task \
    public.ecr.aws/lambda/python:3.11 \
    pip install h3 psycopg2-binary boto3 -t . --no-cache-dir

  echo "3. Tworzenie zip..."
  cd "$BUILD_DIR"
  zip -r ../lambda_full_$suffix.zip . -x "*.pyc" -x "__pycache__/*"
  cd ..
  echo "Gotowe: lambda_full_$suffix.zip"
}

if [ "$ARCH" = "arm64" ]; then
  build_for "linux/arm64" "arm"
elif [ "$ARCH" = "amd64" ]; then
  build_for "linux/amd64" "x86"
else
  build_for "linux/amd64" "x86"
  build_for "linux/arm64" "arm"
fi

echo ""
echo "Wgraj odpowiedni zip:"
echo "  - Lambda x86_64 -> lambda_full_x86.zip"
echo "  - Lambda arm64  -> lambda_full_arm.zip"

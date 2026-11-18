#!/usr/bin/env bash
# Prepara la super-resolution (EDSR x2) usata da tools/news.py per le carte piccole.
# Uso: bash tools/setup_sr.sh <cartella>   poi   export GAHUB_SR=<cartella>
set -e
D="${1:?cartella di destinazione}"
mkdir -p "$D"
pip install -q --target "$D/pylib" "opencv-contrib-python-headless<5" "numpy<2.3"
[ -s "$D/EDSR_x2.pb" ] || curl -sSL -o "$D/EDSR_x2.pb" https://raw.githubusercontent.com/Saafke/EDSR_Tensorflow/master/models/EDSR_x2.pb
echo "pronto: export GAHUB_SR=$D"

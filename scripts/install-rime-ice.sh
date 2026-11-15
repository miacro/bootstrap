#!/bin/bash

RIME_URL=https://github.com/iDvel/rime-ice.git
RIME_DIR=~/.local/share/fcitx5/rime
RIME_CFG=~/.local/share/fcitx5/rime/default.custom.yaml
if [ ! -d ${RIME_DIR}/.git ]; then
    mkdir -p ${RIME_DIR};
    git clone --depth 1 ${RIME_URL} ${RIME_DIR};
fi
if [ ! -f "${RIME_CFG}" ]; then
    echo "patch:" > ${RIME_CFG};
    echo '    "menu/page_size": 9' >> ${RIME_CFG};
fi
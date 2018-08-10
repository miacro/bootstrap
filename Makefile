CACHE_DIR=`pwd`/repository
SHELL=/bin/bash

# options
GIT_BASE_URI=$$(dirname $$(git remote get-url origin))
REPO_NAME=""
INSTALL_DIR=${HOME}
TARGET=reinstall
MAKE=make --no-print-directory
sinclude .Makefile

install:
	@  [[ ! -n ${REPO_NAME} ]] \
	&& echo "unspecified REPO_NAME" \
	&& exit 0 \
	|| ${MAKE} install-repo

config:
	@  ${MAKE} REPO_NAME=profiles TARGET=install-dotfiles install-repo \
	&& ${MAKE} REPO_NAME=utils install-repo \
	&& ${MAKE} REPO_NAME=emacs.d install-repo \
	&& ${MAKE} REPO_NAME=vim.d install-repo \
	&& ${MAKE} REPO_NAME=stumpwm.d TARGET=relink install-repo

all:
	@  ${MAKE} config \
	&& ${MAKE} REPO_NAME=bootstrap prepare-repo \
	&& ${MAKE} REPO_NAME=nginx.d prepare-repo \
	&& ${MAKE} REPO_NAME=lisp-koans prepare-repo \
	&& ${MAKE} REPO_NAME=miacropp prepare-repo \
	&& ${MAKE} REPO_NAME=minesweeper prepare-repo \
	&& ${MAKE} REPO_NAME=command-line-options prepare-repo \
	&& ${MAKE} REPO_NAME=online-judge prepare-repo \
	&& ${MAKE} REPO_NAME=pkget prepare-repo \
	&& ${MAKE} REPO_NAME=mlmisc prepare-repo \
	&& ${MAKE} REPO_NAME=repomisc prepare-repo \
	&& ${MAKE} REPO_NAME=easycert prepare-repo \
	&& ${MAKE} REPO_NAME=pyconfigmanager prepare-repo \
	&& ${MAKE} REPO_NAME=dockerwrapper prepare-repo \
	&& ${MAKE} REPO_NAME=miacro.github.com prepare-repo \
	&& ${MAKE} REPO_NAME=miacro-overlay prepare-repo

install-quicklisp:
	@  curl https://beta.quicklisp.org/quicklisp.lisp > /tmp/quicklisp.lisp \
	&& curl https://beta.quicklisp.org/quicklisp.lisp.asc > /tmp/quicklisp.lisp.asc \
	&& gpg --keyserver pgp.mit.edu --recv-keys 028B5FF7 \
	&& gpg --verify /tmp/quicklisp.lisp.asc /tmp/quicklisp.lisp \
	&& sbcl --load /tmp/quicklisp.lisp --eval "(quicklisp-quickstart:install)" --quit


# component
prepare-cache-dir:
	@  [[ -d ${CACHE_DIR} ]] || mkdir -p ${CACHE_DIR}

clone-repo: prepare-cache-dir
	git clone ${GIT_BASE_URI}/${REPO_NAME} ${CACHE_DIR}/${REPO_NAME}

update-repo: prepare-cache-dir
	@  cd ${CACHE_DIR}/${REPO_NAME} && git pull

prepare-repo:
	@  [[ -d ${CACHE_DIR}/${REPO_NAME}/.git ]] \
	&& ${MAKE} update-repo \
	|| ${MAKE} clone-repo

install-repo: prepare-repo
	@  echo "installing repo ${REPO_NAME}" \
	&& ${MAKE} -C ${CACHE_DIR}/${REPO_NAME} ${TARGET}

.PHONY: prepare-cache-dir prepare-repo all install

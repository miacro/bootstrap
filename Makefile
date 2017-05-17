CACHE_DIR=`pwd`/repository
SHELL=/bin/bash

# options
GIT_BASE_URI="git@github.com:miacro"
REPO_NAME=""
INSTALL_DIR=${HOME}
TARGET=reinstall
MAKE=make --no-print-directory
sinclude .makefile

install:
	@  [[ ! -n ${REPO_NAME} ]] \
	&& echo "unspecified REPO_NAME" \
	&& exit 0 \
	|| ${MAKE} install-repo

config:
	@  ${MAKE} REPO_NAME=dotfiles  install-repo \
	&& ${MAKE} REPO_NAME=utils install-repo \
	&& ${MAKE} REPO_NAME=emacs.d install-repo \
	&& ${MAKE} REPO_NAME=awesome.d install-repo \
	&& ${MAKE} REPO_NAME=vim.d install-repo \
	&& ${MAKE} REPO_NAME=stumpwm.d install-repo

all:
	@  ${MAKE} REPO_NAME=dotfiles  install-repo \
	&& ${MAKE} REPO_NAME=utils install-repo \
	&& ${MAKE} REPO_NAME=emacs.d install-repo \
	&& ${MAKE} REPO_NAME=awesome.d install-repo \
	&& ${MAKE} REPO_NAME=vim.d install-repo \
	&& ${MAKE} REPO_NAME=stumpwm.d install-repo \
	&& ${MAKE} REPO_NAME=system-config prepare-repo \
	&& ${MAKE} REPO_NAME=bootstrap prepare-repo \
	&& ${MAKE} REPO_NAME=nginx.d prepare-repo \
	&& ${MAKE} REPO_NAME=sudoku prepare-repo \
	&& ${MAKE} REPO_NAME=lisp-koans prepare-repo \
	&& ${MAKE} REPO_NAME=miacropp prepare-repo \
	&& ${MAKE} REPO_NAME=minesweeper prepare-repo \
	&& ${MAKE} REPO_NAME=command-line-options prepare-repo \
	&& ${MAKE} REPO_NAME=online-judge prepare-repo 

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

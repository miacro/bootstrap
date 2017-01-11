CACHE_DIR=`pwd`/repository

# options
GIT_BASE_URI="git@github.com:miacro"
REPO_NAME=""
INSTALL_DIR=${HOME}
MAKE=make --no-print-directory

nothing:
	@  exit 0

all: dotfiles bootstrap utils emacs.me system-config vim.me \
	   stumpwm.d nginx.d sudoku lisp-koans awesome.d miacropp \
		 online-judge mlisp
	@ exit 0

dotfiles: 
	@  ${MAKE} REPO_NAME=dotfiles  prepare-repo \
	&& ${MAKE} -C ${CACHE_DIR}/dotfiles

bootstrap: 
	@  ${MAKE} REPO_NAME=bootstrap prepare-repo

utils: 
	@  ${MAKE} REPO_NAME=utils prepare-repo \
	&& ${MAKE} -C ${CACHE_DIR}/utils

emacs.me: 
	@  ${MAKE} REPO_NAME=emacs.me prepare-repo \
	&& ${MAKE} -C ${CACHE_DIR}/emacs.me

system-config: 
	@  ${MAKE} REPO_NAME=system-config prepare-repo

vim.me: 
	@  ${MAKE} REPO_NAME=vim.me prepare-repo \
	&& ${MAKE} -C ${CACHE_DIR}/vim.me

stumpwm.d: 
	@  ${MAKE} REPO_NAME=stumpwm.d prepare-repo \
  && ${MAKE} -C ${CACHE_DIR}/stumpwm.d
nginx.d: 
	@  ${MAKE} REPO_NAME=nginx.d prepare-repo

sudoku: 
	@  ${MAKE} REPO_NAME=sudoku prepare-repo

mlisp: 
	@  ${MAKE} REPO_NAME=mlisp prepare-repo

lisp-koans: 
	@  ${MAKE} REPO_NAME=lisp-koans prepare-repo

awesome.d: 
	@  ${MAKE} REPO_NAME=awesome.d prepare-repo

miacropp: 
	@  ${MAKE} REPO_NAME=miacropp prepare-repo
 
online-judge: 
	@  ${MAKE} REPO_NAME=online-judge prepare-repo

# component
reinstall:
	@  stow -d ${CACHE_DIR} -t ${INSTALL_DIR} -R ${REPO_NAME}

install:
	@  stow -d ${CACHE_DIR} -t ${INSTALL_DIR} ${REPO_NAME}

uninstall:
	@  stow -d ${CACHE_DIR} -t ${INSTALL_DIR} -D ${REPO_NAME}

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

.PHONY: nothing prepare-cache-dir clone-repo update-repo prepare-repo 

.PHONY: reinstall uninstall install

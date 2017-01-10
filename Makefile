CACHE_DIR=`pwd`/repository

# options
GIT_BASE_URI="git@github.com:miacro"
REPO_NAME=""
INSTALL_DIR=${HOME}
MAKE_OPTIONS="--no-print-directory"

nothing:
	@echo ""

all: dotfiles bootstrap utils emacs.d system-config vim.d \
	   stumpwm.d nginx.d awesome.d miacropp online-judge
	@echo "done"

dotfiles: 
	@make ${MAKE_OPTIONS} REPO_NAME=dotfiles  prepare-repo

bootstrap: 
	@make ${MAKE_OPTIONS} REPO_NAME=bootstrap prepare-repo

utils: 
	@make ${MAKE_OPTIONS} REPO_NAME=utils prepare-repo

emacs.d: 
	@make ${MAKE_OPTIONS} REPO_NAME=emacs.d prepare-repo

system-config: 
	@make ${MAKE_OPTIONS} REPO_NAME=system-config prepare-repo

vim.d: 
	@make ${MAKE_OPTIONS} REPO_NAME=vim.d prepare-repo

stumpwm.d: 
	@make ${MAKE_OPTIONS} REPO_NAME=stumpwm.d prepare-repo

nginx.d: 
	@make ${MAKE_OPTIONS} REPO_NAME=nginx.d prepare-repo

awesome.d: 
	@make ${MAKE_OPTIONS} REPO_NAME=awesome.d prepare-repo

miacropp: 
	@make ${MAKE_OPTIONS} REPO_NAME=miacropp prepare-repo

online-judge: 
	@make ${MAKE_OPTIONS} REPO_NAME=online-judge prepare-repo

# component
reinstall:
	@stow -d ${CACHE_DIR} -t ${INSTALL_DIR} -R ${REPO_NAME}

install:
	@stow -d ${CACHE_DIR} -t ${INSTALL_DIR} ${REPO_NAME}

uninstall:
	@stow -d ${CACHE_DIR} -t ${INSTALL_DIR} -D ${REPO_NAME}

prepare-cache-dir:
	@[[ -d ${CACHE_DIR} ]] || mkdir -p ${CACHE_DIR}

clone-repo: prepare-cache-dir
	git clone ${GIT_BASE_URI}/${REPO_NAME} ${CACHE_DIR}/${REPO_NAME}

update-repo: prepare-cache-dir
	@cd ${CACHE_DIR}/${REPO_NAME} && git pull

prepare-repo:
	@[[ -d ${CACHE_DIR}/${REPO_NAME}/.git ]] \
		&& make update-repo \
		|| make clone-repo

.PHONY: nothing prepare-cache-dir clone-repo update-repo prepare-repo 

.PHONY: reinstall uninstall install

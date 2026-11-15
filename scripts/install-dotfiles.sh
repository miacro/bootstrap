#!/bin/bash
GIT_BASE_URI=$(dirname $(git remote get-url origin))
vcsh clone "${GIT_BASE_URI}/dotfiles"
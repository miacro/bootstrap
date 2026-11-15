#!/bin/bash
QL_URL=https://beta.quicklisp.org/quicklisp.lisp
QL_TMP=/tmp/quicklisp.lisp

curl ${QL_URL} > ${QL_TMP} \
	&& curl ${QL_URL}.asc > ${QL_TMP}.asc \
	&& gpg --keyserver pgp.mit.edu --recv-keys 028B5FF7 \
	&& gpg --verify ${QL_TMP}.asc ${QL_TMP} \
	&& sbcl --load ${QL_TMP} --eval "(quicklisp-quickstart:install)" --quit
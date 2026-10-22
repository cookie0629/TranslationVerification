CC ?= gcc
CFLAGS ?= -std=c99 -O2 -Wall -Wextra -pedantic

all: funny_parser

funny_parser: parser.c ../HW1_FunnyLexer_C/main.c
	$(CC) $(CFLAGS) parser.c -o funny_parser

test: funny_parser
	python tests/run_tests.py ./funny_parser

clean:
	rm -f funny_parser funny_parser.exe

.PHONY: all test clean

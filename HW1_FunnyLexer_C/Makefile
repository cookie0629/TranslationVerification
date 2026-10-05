CC ?= gcc
CFLAGS ?= -std=c99 -O2 -Wall -Wextra -pedantic

all: funny_hw1

funny_hw1: main.c
	$(CC) $(CFLAGS) main.c -o funny_hw1

run: funny_hw1
	./funny_hw1

clean:
	rm -f funny_hw1 funny_hw1.exe funny_dfa.json funny_dfa.csv

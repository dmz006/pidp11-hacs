#!/usr/bin/env bash
# Login shell for the pdp11 SSH user — attaches to the running SimH screen session.
# Connect with:  ssh pdp11@<host> -p 2211
exec sudo /usr/bin/screen -x pidp11

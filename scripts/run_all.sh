#!/usr/bin/env bash
# Run each TeamReady agent as its own process (recommended for Agentverse mailbox mode).
# Logs go to logs/<agent>.log. Stop everything with: kill $(cat logs/pids)
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
: > logs/pids
for a in knowledge_agent routing_agent manager_agent insights_agent tracker_agent canary_agent orchestrator; do
  python agents/$a.py > logs/$a.log 2>&1 &
  echo $! >> logs/pids
  echo "started $a (pid $!)"
done
echo "Logs: tail -f logs/*.log   Stop: kill \$(cat logs/pids)"

import cProfile
import pstats
import sys

sys.path.insert(0, "src")
from fpl_agent.database.connection import get_connection
from fpl_agent.monitoring.dashboard import generate_dashboard_html

conn = get_connection()
profiler = cProfile.Profile()
profiler.enable()
generate_dashboard_html(conn, live_payload=None)
profiler.disable()
conn.close()

stats = pstats.Stats(profiler)
stats.sort_stats("cumulative")
stats.print_stats(25)

from db import connect
c = connect()
print("reports:", c.execute("SELECT count(*) FROM reports").fetchone()[0],
      "| calls:", c.execute("SELECT count(*) FROM calls").fetchone()[0],
      "| market:", c.execute("SELECT count(*) FROM market_reports").fetchone()[0])
print("\n== broker distribution (top 15) ==")
for r in c.execute("SELECT COALESCE(broker,'<null>') b, count(*) n FROM reports GROUP BY b ORDER BY n DESC LIMIT 15"):
    print(f"  {r['n']:3}  {r['b']}")
print("\n== unknown/null broker report filenames (first 20) ==")
for r in c.execute("SELECT filename FROM reports WHERE broker IS NULL OR broker='' OR broker='Unknown' LIMIT 20"):
    print("   ", r["filename"][:70])
print("\n== market report themes/sectors ==")
for r in c.execute("SELECT theme, sectors_json FROM market_reports"):
    print("   ", (r["theme"] or "")[:50], "|", (r["sectors_json"] or "")[:60])

"""Quick test script for Laserfiche connector."""
import asyncio
import sys

sys.stdout.reconfigure(encoding='utf-8')

async def main():
    from connectors.laserfiche import LaserficheConnector
    
    conn = LaserficheConnector()
    try:
        print("=== Test 1: Agenda Packets RSS ===")
        items = await conn._fetch_rss("5321")
        print(f"Found {len(items)} items")
        for item in items[:3]:
            print(f"  {item['title']} (folder={item['is_folder']}, doc={item['is_document']}, id={item['entity_id']})")
        
        print()
        print("=== Test 2: Current Year Folder ===")
        year_id = await conn._get_current_year_folder_id()
        print(f"Year folder ID: {year_id}")
        
        print()
        print("=== Test 3: Year Folder Contents ===")
        if year_id:
            meetings = await conn._fetch_rss(year_id)
            print(f"Found {len(meetings)} items")
            for m in meetings[:3]:
                print(f"  {m['title']} (folder={m['is_folder']}, doc={m['is_document']}, id={m['entity_id']})")
        
        print()
        print("=== Test 4: fetch_agenda_list ===")
        agendas = await conn.fetch_agenda_list(limit=3)
        print(f"Found {len(agendas)} agendas")
        for a in agendas:
            print(f"  {a['title']} - {a['meeting_date']} - pdf_url={a['pdf_url']}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())

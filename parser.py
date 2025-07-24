import os
import json
from bs4 import BeautifulSoup

def find_html_files(start_path):
    """
    Find all 'main' HTML files in a directory, ignoring partials found in subdirectories.
    It prioritizes index.html at the root.
    """
    html_files = []
    # We walk the directory but explicitly tell walk not to descend into 'files' dirs,
    # which is where Tilda stores partial body HTMLs.
    for root, dirs, files in os.walk(start_path):
        if 'files' in dirs:
            dirs.remove('files')

        for file in files:
            if file.lower().endswith('.html'):
                full_path = os.path.join(root, file)
                # Give priority to the root index.html
                if file.lower() == 'index.html' and root == start_path:
                    html_files.insert(0, full_path)
                else:
                    html_files.append(full_path)
    return html_files

def get_combined_soup(main_file_path):
    """
    Loads the main HTML file and combines it with its corresponding 'body' file if it exists.
    Tilda often splits the head/header and the body content into separate files.
    """
    with open(main_file_path, 'r', encoding='utf-8') as f:
        main_soup = BeautifulSoup(f.read(), 'lxml')

    # Construct the potential path for the body file
    # e.g., page123.html -> files/page123body.html
    dir_name = os.path.dirname(main_file_path)
    file_name = os.path.basename(main_file_path)
    body_file_name = file_name.replace('.html', 'body.html')
    body_file_path = os.path.join(dir_name, 'files', body_file_name)

    if os.path.exists(body_file_path):
        with open(body_file_path, 'r', encoding='utf-8') as f:
            body_soup = BeautifulSoup(f.read(), 'lxml')

        # The main content of the page is usually within a div with id="allrecords"
        main_content_container = main_soup.find('div', id='allrecords')
        body_content = body_soup.find('div', id='allrecords')

        if main_content_container and body_content:
            # Replace the container's content with the content from the body file
            main_content_container.clear()
            for child in body_content.find_all(recursive=False):
                main_content_container.append(child)

    return main_soup


def get_page_slug(filepath, soup):
    """Determine the page slug from the file or a meta tag."""
    # Try to get slug from <meta property="og:url">
    og_url_tag = soup.find('meta', property='og:url')
    if og_url_tag and og_url_tag.get('content'):
        # Extract full path from URL, preserving hierarchical structure
        full_url = og_url_tag['content'].strip()
        
        # Parse the URL to get just the path component
        from urllib.parse import urlparse
        parsed_url = urlparse(full_url)
        path = parsed_url.path
        
        # Remove .html extension if present and ensure it starts with /
        if path.endswith('.html'):
            path = path[:-5]  # Remove .html
        
        # Handle root path
        if not path or path == '/':
            return '/'
        
        # Ensure the path starts with /
        if not path.startswith('/'):
            path = '/' + path
            
        return path

    # Fallback to filename
    slug = os.path.basename(filepath).replace('.html', '')
    if slug.lower() == 'index':
        return '/'
    return f"/{slug}"

def parse_menu(soup, debug=False):
    """
    Extracts the main menu and submenus from the Tilda page soup.
    Supports multiple Tilda menu structures (T228, T456, etc.).
    """
    menu = []
    
    if debug:
        print("🔍 Starting menu parsing...")
    
    # Try different navigation patterns used by Tilda
    navigation_selectors = [
        # T228 pattern (original)
        'nav.t228__centercontainer',
        # T456 pattern  
        'nav.t456__rightwrapper',
        # Generic patterns as fallbacks
        'nav.t-menu',
        'div.t-menu',
        # Look for any nav with menu classes
        'nav[class*="menu"]',
        'div[class*="menu"]'
    ]
    
    main_nav = None
    menu_list_selector = None
    
    # Find the navigation container
    for selector in navigation_selectors:
        main_nav = soup.select_one(selector)
        if main_nav:
            if debug:
                print(f"✅ Found navigation with selector: {selector}")
                print(f"   Classes: {main_nav.get('class', [])}")
            
            # Determine the appropriate list item selector based on found nav
            if 't228' in main_nav.get('class', []):
                menu_list_selector = '.t228__list_item > a.t-menu__link-item'
            elif 't456' in main_nav.get('class', []):
                menu_list_selector = '.t456__list_item > a.t-menu__link-item'
            else:
                # Generic fallback
                menu_list_selector = 'a.t-menu__link-item'
            
            if debug:
                print(f"   Using menu list selector: {menu_list_selector}")
            break
    
    if not main_nav:
        # Final fallback: look for any ul with menu-related classes
        main_nav = soup.select_one('ul.t-menu__list, ul[class*="menu"], ul[class*="list"]')
        if main_nav:
            menu_list_selector = 'a.t-menu__link-item'
            if debug:
                print(f"✅ Found navigation with fallback UL selector")
                print(f"   Classes: {main_nav.get('class', [])}")
    
    if not main_nav:
        if debug:
            print("❌ No navigation container found")
        return []

    # Find all top-level menu items
    main_menu_links = main_nav.select(menu_list_selector)
    
    if debug:
        print(f"🔗 Found {len(main_menu_links)} menu links with selector: {menu_list_selector}")
    
    # If no links found, try alternative selectors
    if not main_menu_links:
        alternative_selectors = [
            'a.t-menu__link-item',
            'a[class*="menu"]',
            'li > a'
        ]
        for alt_selector in alternative_selectors:
            main_menu_links = main_nav.select(alt_selector)
            if main_menu_links:
                if debug:
                    print(f"✅ Found {len(main_menu_links)} links with alternative selector: {alt_selector}")
                break

    if debug and not main_menu_links:
        print("❌ No menu links found with any selector")
        # Show available links for debugging
        all_links = main_nav.find_all('a')
        print(f"   Available links in nav: {len(all_links)}")
        for i, link in enumerate(all_links[:5]):  # Show first 5
            print(f"   {i+1}. {link.get_text(strip=True)} -> {link.get('href', '')}")

    for i, link in enumerate(main_menu_links):
        title = link.get_text(strip=True)
        href = link.get('href', '')
        
        if debug:
            print(f"\n📋 Processing menu item {i+1}: '{title}' -> '{href}'")
        
        # Skip empty titles or obvious non-menu items
        if not title or title.lower() in ['menu', '']:
            if debug:
                print(f"   ⏭️ Skipping empty/invalid title")
            continue
        
        menu_item = {"title": title}

        # Case 1: Item has a submenu
        if href.startswith('#submenu:'):
            if debug:
                print(f"   🔽 Submenu detected: {href}")
            
            # Handle both "#submenu:HVAC" and "#submenu: HVAC" (with space)
            submenu_hook = href.strip()
            submenu_container = soup.find('div', {'data-tooltip-hook': submenu_hook})
            
            # If exact match fails, try with/without spaces
            if not submenu_container:
                # Try without space after colon
                normalized_hook = href.replace('#submenu: ', '#submenu:')
                submenu_container = soup.find('div', {'data-tooltip-hook': normalized_hook})
                if debug and submenu_container:
                    print(f"   ✅ Found submenu with normalized hook (no space): {normalized_hook}")
            
            if not submenu_container:
                # Try with space after colon  
                normalized_hook = href.replace('#submenu:', '#submenu: ')
                submenu_container = soup.find('div', {'data-tooltip-hook': normalized_hook})
                if debug and submenu_container:
                    print(f"   ✅ Found submenu with normalized hook (with space): {normalized_hook}")
            
            if submenu_container:
                submenu_list = []
                # Look for submenu links with multiple possible selectors
                submenu_selectors = [
                    '.t794__list_item a',
                    '.t794__link',
                    'a[role="menuitem"]',
                    'li a',
                    'a'
                ]
                
                submenu_links = []
                for sub_selector in submenu_selectors:
                    submenu_links = submenu_container.select(sub_selector)
                    if submenu_links:
                        if debug:
                            print(f"   📎 Found {len(submenu_links)} submenu links with: {sub_selector}")
                        break
                
                for j, sub_link in enumerate(submenu_links):
                    sub_title = sub_link.get_text(strip=True)
                    sub_href = sub_link.get('href', '')
                    
                    if debug:
                        print(f"     {j+1}. '{sub_title}' -> '{sub_href}'")
                    
                    # Skip empty titles
                    if not sub_title:
                        continue
                    
                    # Ensure slug has a leading slash
                    if sub_href and not sub_href.startswith(('http', 'mailto:', 'tel:')):
                        sub_slug = sub_href if sub_href.startswith('/') else f"/{sub_href}"
                    else:
                        sub_slug = sub_href
                        
                    submenu_list.append({"title": sub_title, "slug": sub_slug})
                
                if submenu_list:
                    # The parent's slug is derived from its first child or the submenu name
                    first_child_slug = submenu_list[0]['slug']
                    # Try to create a logical parent slug
                    if '/' in first_child_slug and first_child_slug.count('/') > 1:
                        # Extract parent path (e.g., /hvac-services/repair -> /hvac-services)
                        parent_parts = first_child_slug.split('/')[:-1]
                        menu_item['slug'] = '/'.join(parent_parts) if len(parent_parts) > 1 else '/'
                    else:
                        # Use the title as the slug
                        menu_item['slug'] = f"/{title.lower().replace(' ', '-')}"
                    
                    menu_item['submenu'] = submenu_list
                    
                    if debug:
                        print(f"   ✅ Created submenu with {len(submenu_list)} items, parent slug: {menu_item['slug']}")
                else:
                    # A dropdown menu without content
                    menu_item['slug'] = f"/{title.lower().replace(' ', '-')}"
                    if debug:
                        print(f"   ⚠️ Submenu container found but no links extracted")
            else:
                # Submenu hook found but no container - create a placeholder
                menu_item['slug'] = f"/{title.lower().replace(' ', '-')}"
                if debug:
                    print(f"   ❌ Submenu hook found but no container: {href}")
                
        # Case 2: Item is a direct link
        else:
            if href.startswith('/'):
                menu_item['slug'] = href
            elif href.endswith('.html'):
                slug = href.replace('.html', '')
                menu_item['slug'] = '/' if slug == 'index' else f'/{slug}'
            elif href.startswith(('http', 'mailto:', 'tel:')):
                # Keep external links, emails, and phone numbers as they are
                menu_item['slug'] = href
            else:
                # Default case: create slug from title
                menu_item['slug'] = f"/{title.lower().replace(' ', '-')}"
            
            if debug:
                print(f"   🔗 Direct link, slug: {menu_item['slug']}")
        
        menu.append(menu_item)

    if debug:
        print(f"\n🎉 Menu parsing complete! Found {len(menu)} top-level menu items")
        for item in menu:
            submenu_count = len(item.get('submenu', []))
            submenu_text = f" ({submenu_count} subitems)" if submenu_count > 0 else ""
            print(f"   - {item['title']} -> {item['slug']}{submenu_text}")

    return menu

def parse_page_content(soup, include_images=True):
    """Extract structured content from a BeautifulSoup object, focusing on Tilda-specific elements while maintaining document order."""
    content = []
    
    # Find the main content container, which in Tilda is usually #allrecords
    main_content = soup.find('div', id='allrecords')
    
    if not main_content:
        # Fallback to body if #allrecords is not found
        main_content = soup.body
        if not main_content:
            return []

    # To avoid parsing navigation as content, we decompose (remove) the header and footer.
    header = main_content.find('header', id='t-header')
    if header:
        header.decompose()
        
    footer = main_content.find('footer', id='t-footer')
    if footer:
        footer.decompose()

    # Remove navigation and menu elements
    for nav in main_content.find_all(['nav', 'div'], class_=lambda x: x and any(menu_class in x for menu_class in ['t228', 't794', 't-menu'])):
        nav.decompose()

    # Track processed content to avoid duplicates
    processed_texts = set()
    processed_elements = set()

    # Collect all potential content elements with their position information
    content_candidates = []

    # Get all elements that could contain content, preserving document order
    all_elements = main_content.find_all(True, recursive=True)
    
    for element in all_elements:
        # Skip if we've already processed this element or if it's in navigation
        if (id(element) in processed_elements or
            element.find_parent(['nav', 'header', 'footer']) or
            any(nav_class in element.get('class', []) for nav_class in ['t228', 't794', 't-menu'])):
            continue

        element_info = None
        element_classes = element.get('class', [])
        
        # PRIORITY 1: tn-atom elements (Tilda's main text containers)
        if 'tn-atom' in element_classes:
            # Skip empty atoms or those containing only images
            if element.find('img') and not element.get_text(strip=True):
                continue
                
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                # Check if this looks like a heading
                is_heading = (len(text_content) < 150 and 
                            (text_content.isupper() or 
                             text_content.istitle() or 
                             element.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']) or
                             'font-weight:700' in element.get('style', '') or
                             'font-weight:600' in element.get('style', '')))
                
                element_info = {
                    "type": "heading" if is_heading else "paragraph",
                    "text": text_content,
                    "priority": 1
                }

        # PRIORITY 2: FAQ titles (spans with specific classes)
        elif (element.name == 'span' and 
              any(title_class in element_classes for title_class in 
                  ['t585__title', 't567__title', 't221__title', 't205__title', 't-name', 't-title', '__title', '__name'])):
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                element_info = {
                    "type": "heading",
                    "text": text_content,
                    "priority": 2
                }

        # PRIORITY 3: FAQ content and other structured content
        elif (element.name in ['div', 'span', 'p'] and
              any(content_class in element_classes for content_class in 
                  ['t585__content', 't585__text', 't567__content', 't567__text',
                   't221__content', 't221__text', 't205__content', 't205__text',
                   't-descr', '__content', '__text'])):
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                element_info = {
                    "type": "paragraph",
                    "text": text_content,
                    "priority": 3
                }

        # PRIORITY 4: t396 elements with text content
        elif (any('t396__elem' in cls for cls in element_classes) and 
              element.get('data-elem-type') == 'text' and
              not element.find('div', class_='tn-atom')):  # Don't double-process tn-atom parents
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                is_heading = (len(text_content) < 150 and 
                            (text_content.isupper() or text_content.istitle()))
                element_info = {
                    "type": "heading" if is_heading else "paragraph",
                    "text": text_content,
                    "priority": 4
                }

        # PRIORITY 5: Traditional Tilda block content
        elif (element.name in ['p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'] and
              any(text_class in element_classes for text_class in ['t-text', 't-title', 't-descr', 't-name'])):
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                is_heading = (element.name.startswith('h') or 
                            't-title' in element_classes or
                            't-name' in element_classes)
                element_info = {
                    "type": "heading" if is_heading else "paragraph",
                    "text": text_content,
                    "priority": 5
                }

        # PRIORITY 6: Standard HTML headings and paragraphs
        elif (element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p'] and
              not element.find_parent('div', class_='tn-atom') and
              not element.find_parent('div', class_=lambda x: x and 't396__elem' in x)):
            text_content = element.get_text(strip=True)
            if text_content and len(text_content) > 3 and text_content not in processed_texts:
                element_info = {
                    "type": "heading" if element.name.startswith('h') else "paragraph",
                    "text": text_content,
                    "priority": 6
                }

        # PRIORITY 7: Buttons and important links
        elif (element.name in ['a', 'button'] and
              any(btn_class in element_classes for btn_class in ['t-btn', 'tn-atom']) and
              not element.find_parent(['nav', 'header', 'footer'])):
            button_text = element.get_text(strip=True)
            if (button_text and len(button_text) > 2 and len(button_text) < 50 and 
                button_text not in processed_texts and
                not button_text.lower() in ['call us', 'contact', 'menu', 'home']):
                element_info = {
                    "type": "button",
                    "text": button_text,
                    "href": element.get('href', ''),
                    "priority": 7
                }

        # PRIORITY 8: Images (only if include_images is True)
        elif element.name == 'img' and include_images:
            src = element.get('src') or element.get('data-original')
            alt = element.get('alt', '')
            if src and not src.startswith('data:'):  # Exclude base64 embedded images
                element_info = {
                    "type": "image",
                    "src": src,
                    "alt": alt,
                    "priority": 8
                }

        # PRIORITY 9: Lists
        elif (element.name in ['ul', 'ol'] and
              not element.find_parent('div', class_=lambda x: x and any(nav_class in x for nav_class in ['t228', 't794', 't-menu']))):
            items = []
            for li in element.find_all('li'):
                li_text = li.get_text(strip=True)
                if li_text and li_text not in processed_texts:
                    items.append(li_text)
            
            if items and len(items) > 1:  # Only include lists with multiple items
                element_info = {
                    "type": "list",
                    "items": items,
                    "priority": 9
                }
                # Mark all list item texts as processed
                for item in items:
                    processed_texts.add(item)

        # If we found content, add it to candidates with position info
        if element_info:
            # Calculate the element's position in the document for sorting
            position = 0
            current = element
            while current.previous_sibling:
                current = current.previous_sibling
                position += 1
            
            # Add parent positions for more accurate sorting
            parent_positions = []
            parent = element.parent
            while parent and parent != main_content:
                parent_position = 0
                current = parent
                while current.previous_sibling:
                    current = current.previous_sibling
                    parent_position += 1
                parent_positions.append(parent_position)
                parent = parent.parent
            
            element_info['position'] = (tuple(reversed(parent_positions)), position)
            element_info['element'] = element
            content_candidates.append(element_info)
            
            # Mark text as processed
            if 'text' in element_info:
                processed_texts.add(element_info['text'])
            
            # Mark element as processed
            processed_elements.add(id(element))

    # Sort candidates by position to maintain document order
    content_candidates.sort(key=lambda x: x['position'])

    # Convert candidates to final content, removing position metadata
    for candidate in content_candidates:
        final_item = {k: v for k, v in candidate.items() if k not in ['position', 'element', 'priority']}
        content.append(final_item)

    return content

def parse_tilda_export(project_path, include_images=True, debug=False):
    """
    Main function to parse the extracted Tilda project.
    Returns a dictionary with structured pages and menu data.
    """
    extracted_dir = os.path.join(project_path, 'extracted')
    if not os.path.isdir(extracted_dir):
        return {"error": "Extracted directory not found."}
    
    html_files = find_html_files(extracted_dir)
    if not html_files:
        return {"error": "No HTML files found in the export."}

    structured_data = {"pages": [], "menu": []}
    
    if debug:
        print(f"🚀 Starting Tilda export parsing...")
        print(f"   Found {len(html_files)} HTML files")
    
    # First, parse the main page (index.html) to find the menu, since it's shared.
    if html_files:
        if debug:
            print(f"📋 Parsing menu from: {html_files[0]}")
        
        # Get the combined soup to ensure the header is properly loaded
        combined_soup_for_menu = get_combined_soup(html_files[0])
        structured_data['menu'] = parse_menu(combined_soup_for_menu, debug=debug)

    # Then, parse all pages for content
    for i, file_path in enumerate(html_files):
        if debug:
            print(f"\n📄 Parsing page {i+1}/{len(html_files)}: {os.path.basename(file_path)}")
        
        # Get the full, combined soup for the page
        soup = get_combined_soup(file_path)
        
        page_title = soup.title.string.strip() if soup.title else "Untitled"
        page_slug = get_page_slug(file_path, soup)
        page_content = parse_page_content(soup, include_images)
        
        if debug:
            print(f"   Title: {page_title}")
            print(f"   Slug: {page_slug}")
            print(f"   Content blocks: {len(page_content)}")
        
        if page_content:
            structured_data["pages"].append({
                "title": page_title,
                "slug": page_slug,
                "content": page_content
            })

    if debug:
        total_pages = len(structured_data["pages"])
        total_menu_items = len(structured_data["menu"])
        total_content_blocks = sum(len(page.get('content', [])) for page in structured_data["pages"])
        
        print(f"\n🎉 Parsing complete!")
        print(f"   Pages: {total_pages}")
        print(f"   Menu items: {total_menu_items}")
        print(f"   Total content blocks: {total_content_blocks}")

    return structured_data 
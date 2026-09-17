# core/ai_form_filler.py
# AI-powered universal form filler
# Claude reads the full page DOM, identifies every field, fills intelligently
# Works on ANY career site regardless of ATS or custom form structure

import os
import json
import re
import asyncio
from playwright.async_api import Page
import anthropic

from config.profile import PROFILE
from utils.helpers import human_delay, scroll_slowly
from core.captcha_handler import check_and_handle_captcha
from utils.notifier import notify_manual_apply_needed

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

TOBI_PROFILE_JSON = json.dumps({
    "first_name": PROFILE["preferred_name"],
    "last_name": PROFILE["last_name"],
    "email": PROFILE["email"],
    "phone": PROFILE["phone"],
    "location": "Dublin, Ireland",
    "linkedin": PROFILE["linkedin_url"],
    "github": PROFILE["github_url"],
    "current_role": PROFILE["current_role"],
    "current_company": PROFILE["current_company"],
    "years_experience": PROFILE["years_experience"],
    "degree": "MSc Computer Science (Cloud Platforms & Applications)",
    "university": "Griffith College Dublin",
    "graduation_year": "2027",
    "skills": PROFILE["primary_skills"] + PROFILE["ai_ml_skills"][:5],
    "visa_status": "Irish Stamp 2 — eligible for Stamp 1G post-graduation Aug 2027 (24 months full-time work, no permit needed). CSEP sponsorship required after that.",
    "authorized_to_work_ireland": "Yes",
    "requires_sponsorship": "Yes (CSEP after Aug 2027)",
    "salary_expectation": "40000-50000 EUR",
    "available_start": "Immediately / 2 weeks",
    "willing_to_relocate": "No — already in Dublin",
    "work_preference": "Hybrid",
    "nationality": "Nigerian",
    "gender": "Male",
    "ethnicity": "Prefer not to say",
    "disability": "No",
    "veteran_status": "No",
}, indent=2)


async def get_page_form_structure(page: Page) -> str:
    """
    Extract the form structure from the page as a simplified JSON
    that Claude can analyze and create fill instructions for.
    """
    form_data = await page.evaluate("""() => {
        const fields = [];
        
        // Get all interactive form elements
        const elements = document.querySelectorAll(
            'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), ' +
            'select, textarea, ' +
            '[role="combobox"], [role="listbox"], [role="textbox"], ' +
            '[contenteditable="true"]'
        );
        
        elements.forEach((el, index) => {
            if (!el.offsetParent) return; // Skip hidden elements
            
            // Find associated label
            let label = '';
            
            // Method 1: for/id
            if (el.id) {
                const labelEl = document.querySelector(`label[for="${el.id}"]`);
                if (labelEl) label = labelEl.innerText.trim();
            }
            
            // Method 2: aria-label
            if (!label) label = el.getAttribute('aria-label') || '';
            
            // Method 3: aria-labelledby
            if (!label) {
                const labelledById = el.getAttribute('aria-labelledby');
                if (labelledById) {
                    const labelEl = document.getElementById(labelledById);
                    if (labelEl) label = labelEl.innerText.trim();
                }
            }
            
            // Method 4: placeholder
            if (!label) label = el.getAttribute('placeholder') || '';
            
            // Method 5: name
            if (!label) label = el.getAttribute('name') || '';
            
            // Method 6: parent/sibling scan
            if (!label) {
                let node = el.parentElement;
                for (let i = 0; i < 4; i++) {
                    if (!node) break;
                    const lbl = node.querySelector('label, legend, [class*="label"], [class*="title"]');
                    if (lbl && lbl !== el) {
                        label = lbl.innerText.trim();
                        break;
                    }
                    node = node.parentElement;
                }
            }
            
            // Get options for selects
            let options = [];
            if (el.tagName === 'SELECT') {
                options = Array.from(el.options).map(o => o.text.trim()).filter(Boolean).slice(0, 20);
            }
            
            // Get current value
            const currentValue = el.value || el.innerText || '';
            
            fields.push({
                index,
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || el.tagName.toLowerCase(),
                id: el.id || '',
                name: el.getAttribute('name') || '',
                label: label.replace(/\\n/g, ' ').replace(/\\s+/g, ' ').trim().slice(0, 100),
                placeholder: el.getAttribute('placeholder') || '',
                required: el.required || el.getAttribute('aria-required') === 'true',
                options: options,
                current_value: currentValue.slice(0, 50),
                class: (el.className || '').slice(0, 80),
            });
        });
        
        return fields;
    }""")

    return json.dumps(form_data, indent=2)


async def ai_generate_fill_instructions(
    form_structure: str,
    job_title: str,
    company: str,
    cover_letter: str,
    page_url: str
) -> list:
    """
    Send form structure to Claude. Get back precise fill instructions.
    Returns list of { selector_strategy, value, action } objects.
    """
    prompt = f"""
You are filling out a job application form for Tobi Akindele.

JOB: {job_title} at {company}
PAGE: {page_url}

TOBI'S PROFILE:
{TOBI_PROFILE_JSON}

COVER LETTER (use this for any cover letter / motivation fields):
{cover_letter[:800]}

FORM FIELDS DETECTED:
{form_structure}

For each field that needs filling, return a JSON array of fill instructions.
Each instruction must have:
{{
  "field_index": <the index from the form structure>,
  "label": "<the field label>",
  "value": "<exact value to enter>",
  "action": "fill" | "select" | "click_option" | "skip",
  "selector": "<CSS selector or null>",
  "notes": "<any special handling needed>"
}}

Rules:
- Skip fields that are already filled (current_value is not empty)
- Skip hidden fields, submit buttons
- For dropdowns with options listed: pick the best matching option text exactly
- For "area of interest" type fields: select "Technology" or "Software Engineering"  
- For work authorization / right to work: always Yes
- For sponsorship required: Yes
- For salary: 40000-50000 or 45000 if single value needed
- For cover letter / motivation / why us: use the provided cover letter
- For gender/ethnicity/disability: use profile values or "Prefer not to say"
- For unknown free-text questions: write a 2-sentence answer in Tobi's voice, direct, no em dashes
- If a field seems irrelevant or harmful to fill, action = "skip"
- Return ONLY the JSON array, no other text
"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        # Extract JSON array
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"  [AI Form] Instruction generation error: {e}")

    return []


async def execute_fill_instructions(page: Page, instructions: list, form_elements_js: list):
    """
    Execute the fill instructions generated by Claude.
    Uses multiple selector strategies to find and fill each field.
    """
    for instruction in instructions:
        if instruction.get("action") == "skip":
            continue

        idx = instruction.get("field_index")
        value = instruction.get("value", "")
        action = instruction.get("action", "fill")
        label = instruction.get("label", "")
        notes = instruction.get("notes", "")

        if not value:
            continue

        try:
            # Try to find element by index in the JS-extracted list
            target_field = None
            if idx is not None and idx < len(form_elements_js):
                target_field = form_elements_js[idx]

            # Build selector strategies
            selectors = []
            if target_field:
                if target_field.get("id"):
                    selectors.append(f'#{target_field["id"]}')
                if target_field.get("name"):
                    selectors.append(f'[name="{target_field["name"]}"]')
                if target_field.get("class"):
                    # Use first class only
                    first_class = target_field["class"].split()[0] if target_field["class"] else ""
                    if first_class:
                        selectors.append(f'.{first_class}')

            if instruction.get("selector"):
                selectors.insert(0, instruction["selector"])

            # Label-based fallback
            if label:
                selectors.append(f'[aria-label="{label}"]')
                selectors.append(f'[placeholder*="{label[:20]}"]')

            # Try each selector
            filled = False
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    if not await el.is_visible(timeout=500):
                        continue

                    tag = await el.evaluate("el => el.tagName.toLowerCase()")
                    input_type = await el.get_attribute("type") or tag

                    await el.scroll_into_view_if_needed()
                    await human_delay(200, 500)

                    if action == "fill" or input_type in ["text", "email", "tel", "number", "textarea"]:
                        await el.triple_click()
                        await el.fill(str(value))
                        filled = True

                    elif action == "select" or tag == "select":
                        # Try exact match, then partial
                        try:
                            await el.select_option(label=value)
                            filled = True
                        except Exception:
                            try:
                                await el.select_option(value=value)
                                filled = True
                            except Exception:
                                # Try partial match via JS
                                matched = await el.evaluate(f"""(el) => {{
                                    const opts = Array.from(el.options);
                                    const match = opts.find(o =>
                                        o.text.toLowerCase().includes('{value.lower()}') ||
                                        '{value.lower()}'.includes(o.text.toLowerCase().slice(0, 6))
                                    );
                                    if (match) {{ el.value = match.value; el.dispatchEvent(new Event('change')); return true; }}
                                    return false;
                                }}""")
                                filled = bool(matched)

                    elif action == "click_option":
                        # Custom dropdown — click trigger then find option
                        await el.click()
                        await human_delay(600, 1200)
                        # Look for the option text
                        option = page.locator(
                            f'[role="option"]:has-text("{value}"), '
                            f'li:has-text("{value}"), '
                            f'[class*="option"]:has-text("{value}")'
                        ).first
                        if await option.is_visible(timeout=2000):
                            await option.click()
                            filled = True
                        else:
                            # Try search-then-click
                            search_input = page.locator('input[role="searchbox"], input[placeholder*="Search" i]').first
                            if await search_input.is_visible(timeout=1000):
                                await search_input.fill(value[:10])
                                await human_delay(600, 1000)
                                option = page.locator(f'[role="option"]:has-text("{value}")').first
                                if await option.is_visible(timeout=1500):
                                    await option.click()
                                    filled = True

                    if filled:
                        await human_delay(200, 500)
                        break

                except Exception:
                    continue

            if not filled and label:
                print(f"  [AI Form] Could not fill: '{label}'")

        except Exception as e:
            print(f"  [AI Form] Error on field '{label}': {e}")


class AIUniversalFormFiller:
    """
    Fills any job application form using AI.
    Works on any website — LinkedIn, Indeed, Greenhouse, Lever,
    Workday, Taleo, custom ATS, or company-specific forms.
    """

    def __init__(self, page: Page, job_title: str, company: str, cover_letter: str):
        self.page = page
        self.job_title = job_title
        self.company = company
        self.cover_letter = cover_letter

    async def fill(self) -> bool:
        """
        Main entry. Returns True if form was filled successfully.
        """
        print(f"  [AI Form] Reading page structure for {self.company}...")

        # Check for CAPTCHA first
        can_proceed = await check_and_handle_captcha(
            self.page, self.company, self.job_title, self.page.url
        )
        if not can_proceed:
            return False

        # Scroll to load any lazy-rendered fields
        await scroll_slowly(self.page, 800)
        await human_delay(800, 1500)

        # Extract form structure
        form_structure_str = await get_page_form_structure(self.page)
        form_elements = json.loads(form_structure_str)

        if not form_elements:
            print("  [AI Form] No form fields detected on page")
            return False

        print(f"  [AI Form] Found {len(form_elements)} fields — asking Claude to fill...")

        # Get fill instructions from Claude
        instructions = await ai_generate_fill_instructions(
            form_structure=form_structure_str,
            job_title=self.job_title,
            company=self.company,
            cover_letter=self.cover_letter,
            page_url=self.page.url
        )

        if not instructions:
            print("  [AI Form] No fill instructions generated")
            return False

        print(f"  [AI Form] Executing {len(instructions)} fill instructions...")

        # Execute fills
        await execute_fill_instructions(self.page, instructions, form_elements)

        # Check for CAPTCHA again after filling
        await check_and_handle_captcha(
            self.page, self.company, self.job_title, self.page.url
        )

        return True

    async def fill_multi_page_form(self, max_steps: int = 8) -> bool:
        """
        Handle multi-step/multi-page forms.
        Fills each page, clicks Next, repeats until Submit or max steps.
        Returns True if submitted.
        """
        for step in range(1, max_steps + 1):
            print(f"  [AI Form] Step {step}/{max_steps}")

            await self.fill()
            await human_delay(800, 1500)

            # Check for CAPTCHA
            if not await check_and_handle_captcha(
                self.page, self.company, self.job_title, self.page.url
            ):
                return False

            # Look for Submit button
            submit_selectors = [
                'button[type="submit"]:visible',
                'input[type="submit"]:visible',
                'button:has-text("Submit application"):visible',
                'button:has-text("Submit Application"):visible',
                'button:has-text("Submit"):visible',
                'button:has-text("Send application"):visible',
                'a:has-text("Submit"):visible',
            ]
            for sel in submit_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=800):
                        await btn.scroll_into_view_if_needed()
                        await human_delay(500, 1000)
                        await btn.click()
                        await human_delay(2000, 4000)
                        return True
                except Exception:
                    pass

            # Look for Next button
            next_selectors = [
                'button:has-text("Next"):visible',
                'button:has-text("Continue"):visible',
                'button:has-text("Next step"):visible',
                'button[aria-label*="next" i]:visible',
                'a:has-text("Next"):visible',
            ]
            advanced = False
            for sel in next_selectors:
                try:
                    btn = self.page.locator(sel).first
                    if await btn.is_visible(timeout=800):
                        await btn.scroll_into_view_if_needed()
                        await human_delay(400, 800)
                        await btn.click()
                        await human_delay(1500, 3000)
                        advanced = True
                        break
                except Exception:
                    pass

            if not advanced:
                print(f"  [AI Form] No Next/Submit button found at step {step}")
                break

        return False

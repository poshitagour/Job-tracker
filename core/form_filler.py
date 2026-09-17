# core/form_filler.py
# Handles all form field types: text, select, searchable dropdowns,
# multi-select checkboxes, radio buttons, file uploads, textareas

import asyncio
from playwright.async_api import Page
from utils.helpers import human_delay, safe_fill, scroll_slowly
from core.ai_scorer import answer_application_question


class SmartFormFiller:
    """
    Universal form filler. Detects field type and fills intelligently.
    Handles: standard inputs, native selects, custom searchable dropdowns,
    multi-select checkboxes, radio groups, file uploads, textareas.
    """

    def __init__(self, page: Page, profile: dict, job_title: str, company: str, cover_letter: str):
        self.page = page
        self.p = profile
        self.job_title = job_title
        self.company = company
        self.cover_letter = cover_letter

    # ── Main entry ─────────────────────────────────────────────────

    async def fill_all_visible_fields(self):
        """Scan the page and fill every visible form field."""
        await self._fill_standard_inputs()
        await self._fill_native_selects()
        await self._fill_searchable_dropdowns()
        await self._fill_radio_groups()
        await self._fill_checkboxes()
        await self._fill_textareas()

    # ── Standard text inputs ───────────────────────────────────────

    async def _fill_standard_inputs(self):
        inputs = await self.page.query_selector_all('input[type="text"], input[type="email"], input[type="tel"], input[type="number"], input:not([type])')
        for inp in inputs:
            try:
                if not await inp.is_visible():
                    continue
                current = await inp.input_value()
                if current:
                    continue  # already filled

                # Get label
                label = await self._get_label_for(inp)
                value = self._resolve_value(label)

                if not value:
                    # Try AI for unknown fields
                    if label and len(label) > 3:
                        value = answer_application_question(label, self.job_title, self.company)

                if value:
                    await inp.scroll_into_view_if_needed()
                    await human_delay(200, 500)
                    await inp.triple_click()
                    await inp.fill(str(value))
                    await human_delay(200, 400)
            except Exception:
                pass

    # ── Native <select> elements ───────────────────────────────────

    async def _fill_native_selects(self):
        selects = await self.page.query_selector_all('select')
        for sel in selects:
            try:
                if not await sel.is_visible():
                    continue
                label = await self._get_label_for(sel)
                value = self._resolve_select_value(label)
                if not value:
                    continue

                await sel.scroll_into_view_if_needed()
                await human_delay(200, 400)

                # Try by value, then by label text
                options = await sel.query_selector_all('option')
                best_option = None
                for opt in options:
                    opt_text = (await opt.inner_text()).strip().lower()
                    opt_val = (await opt.get_attribute("value") or "").lower()
                    if value.lower() in opt_text or value.lower() in opt_val:
                        best_option = await opt.get_attribute("value")
                        break

                if best_option:
                    await sel.select_option(value=best_option)
                    await human_delay(200, 400)
            except Exception:
                pass

    # ── Custom searchable dropdowns (like Fidelity's) ──────────────

    async def _fill_searchable_dropdowns(self):
        """
        Handles custom dropdowns that are NOT native <select>.
        Pattern: click trigger → search input appears → type → click option.
        Works for: Fidelity, Workday, Greenhouse, Lever, and similar ATS.
        """
        # Find dropdown triggers — buttons or divs that open a dropdown
        triggers = await self.page.query_selector_all(
            '[role="combobox"], [aria-haspopup="listbox"], '
            '[aria-haspopup="true"], .dropdown-toggle, '
            'button[data-toggle="dropdown"], [class*="dropdown"][class*="trigger"], '
            '[class*="select"][class*="container"]'
        )

        for trigger in triggers:
            try:
                if not await trigger.is_visible():
                    continue

                # Get label for this dropdown
                label = await self._get_label_for(trigger)
                if not label:
                    # Try aria-label
                    label = await trigger.get_attribute("aria-label") or ""
                if not label:
                    # Try placeholder
                    label = await trigger.get_attribute("placeholder") or ""

                value = self._resolve_select_value(label)
                if not value:
                    continue

                await trigger.scroll_into_view_if_needed()
                await human_delay(300, 700)

                # Click to open
                await trigger.click()
                await human_delay(500, 1200)

                # Look for a search input that appeared
                search_input = await self.page.query_selector(
                    'input[role="searchbox"], input[placeholder*="Search"], '
                    'input[placeholder*="search"], input[placeholder*="Filter"], '
                    '.dropdown-search input, [class*="search"] input'
                )

                if search_input and await search_input.is_visible():
                    # Type to filter
                    await search_input.fill(value)
                    await human_delay(600, 1200)

                # Find and click matching option
                found = await self._click_best_option(value)

                if not found:
                    # Close dropdown by pressing Escape
                    await self.page.keyboard.press("Escape")

                await human_delay(300, 600)
            except Exception:
                pass

    async def _click_best_option(self, value: str) -> bool:
        """
        Find the best matching option in an open dropdown and click it.
        Handles: listbox options, li items, custom div options.
        """
        option_selectors = [
            '[role="option"]',
            '[role="listbox"] li',
            '[class*="option"]:not(select)',
            '[class*="dropdown"] li',
            '[class*="menu-item"]',
            'ul li[class*="item"]',
            '[class*="choice"]',
        ]

        for sel in option_selectors:
            try:
                options = await self.page.query_selector_all(sel)
                for opt in options:
                    if not await opt.is_visible():
                        continue
                    opt_text = (await opt.inner_text()).strip().lower()
                    if value.lower() in opt_text or opt_text in value.lower():
                        await opt.scroll_into_view_if_needed()
                        await human_delay(200, 400)
                        await opt.click()
                        await human_delay(300, 600)
                        return True
            except Exception:
                pass

        return False

    # ── Multi-select checkboxes (e.g. "Area of Interest") ──────────

    async def _fill_multi_select_checkboxes(self, container_label: str, values_to_select: list):
        """
        Handle multi-select checkboxes like Fidelity's "Area of Interest".
        Opens the dropdown, finds matching checkboxes, ticks them.
        """
        # Find the container/trigger
        triggers = await self.page.query_selector_all('[aria-expanded], button, [role="button"]')
        for trigger in triggers:
            try:
                trigger_text = (await trigger.inner_text()).strip().lower()
                label = await self._get_label_for(trigger)
                if container_label.lower() not in trigger_text and container_label.lower() not in label.lower():
                    continue

                # Open it
                await trigger.click()
                await human_delay(600, 1200)

                # Find checkboxes in the opened panel
                checkboxes = await self.page.query_selector_all('input[type="checkbox"]')
                for cb in checkboxes:
                    try:
                        cb_label = await self._get_label_for(cb)
                        cb_id = await cb.get_attribute("id") or ""
                        label_el = await self.page.query_selector(f'label[for="{cb_id}"]')
                        label_text = (await label_el.inner_text()).strip() if label_el else cb_label

                        for val in values_to_select:
                            if val.lower() in label_text.lower():
                                is_checked = await cb.is_checked()
                                if not is_checked:
                                    await cb.click()
                                    await human_delay(200, 400)
                    except Exception:
                        pass

                # Close or click away
                await self.page.keyboard.press("Escape")
                await human_delay(300, 500)
                return
            except Exception:
                pass

    # ── Radio button groups ────────────────────────────────────────

    async def _fill_radio_groups(self):
        fieldsets = await self.page.query_selector_all('fieldset, [role="radiogroup"]')
        for fieldset in fieldsets:
            try:
                legend = await fieldset.query_selector('legend, [class*="legend"], [class*="label"]')
                if not legend:
                    continue
                label = (await legend.inner_text()).strip().lower()
                value = self._resolve_radio_value(label)
                if not value:
                    continue

                # Find radio buttons
                radios = await fieldset.query_selector_all('input[type="radio"]')
                for radio in radios:
                    try:
                        radio_label_el = await self.page.query_selector(f'label[for="{await radio.get_attribute("id")}"]')
                        radio_text = (await radio_label_el.inner_text()).strip().lower() if radio_label_el else ""
                        radio_val = (await radio.get_attribute("value") or "").lower()

                        if value.lower() in radio_text or value.lower() in radio_val:
                            if not await radio.is_checked():
                                await radio.scroll_into_view_if_needed()
                                await radio.click()
                                await human_delay(200, 400)
                            break
                    except Exception:
                        pass
            except Exception:
                pass

    # ── Checkboxes ─────────────────────────────────────────────────

    async def _fill_checkboxes(self):
        checkboxes = await self.page.query_selector_all('input[type="checkbox"]')
        for cb in checkboxes:
            try:
                if not await cb.is_visible():
                    continue
                label = await self._get_label_for(cb)
                label_lower = label.lower()

                # Auto-tick agreement/consent boxes
                if any(k in label_lower for k in ["agree", "terms", "privacy", "consent", "certify", "confirm"]):
                    if not await cb.is_checked():
                        await cb.click()
                        await human_delay(200, 400)
            except Exception:
                pass

    # ── Textareas ──────────────────────────────────────────────────

    async def _fill_textareas(self):
        textareas = await self.page.query_selector_all('textarea')
        for ta in textareas:
            try:
                if not await ta.is_visible():
                    continue
                current = await ta.input_value()
                if current and len(current) > 50:
                    continue  # Already has meaningful content

                label = await self._get_label_for(ta)
                label_lower = label.lower()

                # Cover letter
                if any(k in label_lower for k in ["cover", "letter", "motivation", "why"]):
                    await ta.scroll_into_view_if_needed()
                    await ta.fill(self.cover_letter)
                    await human_delay(300, 600)

                # General text question — use AI
                elif label and len(label) > 5:
                    answer = answer_application_question(label, self.job_title, self.company)
                    if answer:
                        await ta.scroll_into_view_if_needed()
                        await ta.fill(answer)
                        await human_delay(300, 600)
            except Exception:
                pass

    # ── Label detection ────────────────────────────────────────────

    async def _get_label_for(self, element) -> str:
        """Get the label text for any form element using multiple strategies."""
        try:
            # Strategy 1: for/id pairing
            el_id = await element.get_attribute("id")
            if el_id:
                label_el = await self.page.query_selector(f'label[for="{el_id}"]')
                if label_el:
                    return (await label_el.inner_text()).strip()

            # Strategy 2: aria-label
            aria = await element.get_attribute("aria-label")
            if aria:
                return aria.strip()

            # Strategy 3: aria-labelledby
            labelledby = await element.get_attribute("aria-labelledby")
            if labelledby:
                label_el = await self.page.query_selector(f'#{labelledby}')
                if label_el:
                    return (await label_el.inner_text()).strip()

            # Strategy 4: placeholder
            placeholder = await element.get_attribute("placeholder")
            if placeholder:
                return placeholder.strip()

            # Strategy 5: name attribute
            name = await element.get_attribute("name")
            if name:
                return name.replace("_", " ").replace("-", " ").strip()

            # Strategy 6: preceding sibling/parent label
            label_text = await element.evaluate("""el => {
                // Walk up the DOM to find a label
                let node = el;
                for (let i = 0; i < 5; i++) {
                    node = node.parentElement;
                    if (!node) break;
                    const label = node.querySelector('label, [class*="label"], legend');
                    if (label) return label.innerText.trim();
                }
                // Check previous sibling
                let prev = el.previousElementSibling;
                if (prev) return prev.innerText.trim();
                return '';
            }""")
            return label_text.strip() if label_text else ""

        except Exception:
            return ""

    # ── Value resolution ───────────────────────────────────────────

    def _resolve_value(self, label: str) -> str:
        """Map a label string to the right profile value."""
        p = self.p
        label_lower = label.lower()

        mapping = {
            # Personal
            ("first name", "firstname", "given name"): p.get("preferred_name", ""),
            ("last name", "lastname", "surname", "family name"): p.get("last_name", ""),
            ("full name", "your name"): f"{p.get('preferred_name','')} {p.get('last_name','')}",
            ("email", "e-mail", "email address"): p.get("email", ""),
            ("phone", "mobile", "telephone", "contact number"): p.get("phone", ""),
            ("city", "town"): "Dublin",
            ("location", "current location", "address"): "Dublin, Ireland",
            ("country"): "Ireland",
            ("postcode", "eircode", "postal"): "D07",
            ("linkedin",): p.get("linkedin_url", ""),
            ("github",): p.get("github_url", ""),
            ("portfolio", "website", "personal site"): p.get("portfolio_url", "") or p.get("github_url", ""),

            # Work auth
            ("authorized to work", "right to work", "legal right", "work authorization", "legally authorized"): "Yes",
            ("require sponsor", "need sponsor", "visa sponsor", "require visa support"): "Yes",

            # Education
            ("university", "institution", "college", "school"): p.get("current_university", ""),
            ("degree", "qualification", "highest education", "highest level"): "Master's Degree",
            ("graduation year", "grad year", "year of graduation", "expected graduation"): p.get("current_grad_year", "2027"),
            ("major", "field of study", "course", "programme"): "Computer Science",
            ("gpa", "grade", "result"): "First Class Honours",

            # Work
            ("current company", "employer", "current employer"): p.get("current_company", ""),
            ("current role", "current position", "job title"): p.get("current_role", ""),
            ("years of experience", "years experience", "experience years"): p.get("years_experience", "2"),
            ("notice period", "notice"): "2 weeks",
            ("available", "start date", "availability"): "Immediately / 2 weeks notice",

            # Salary
            ("salary", "expected salary", "salary expectation", "compensation"): "40000-50000",

            # Preferences
            ("remote", "work preference", "work arrangement"): "Hybrid",
            ("relocate", "willing to relocate"): "No",

            # Diversity
            ("gender",): p.get("common_answers", {}).get("gender", "Male"),
            ("ethnicity", "race",): "Prefer not to say",
            ("disability",): "No",
            ("veteran",): "No",
        }

        for keys, value in mapping.items():
            if isinstance(keys, str):
                keys = (keys,)
            if any(k in label_lower for k in keys):
                return value

        return ""

    def _resolve_select_value(self, label: str) -> str:
        """For dropdowns — map label to the right option text."""
        label_lower = label.lower()

        select_mapping = {
            "area of interest": "Technology",
            "interest area": "Technology",
            "department": "Technology",
            "function": "Engineering",
            "business area": "Technology",
            "job category": "Software Engineering",
            "country": "Ireland",
            "location": "Dublin",
            "degree": "Master's",
            "education level": "Master's",
            "work authorization": "Yes",
            "employment type": "Full-time",
            "job type": "Full-time",
            "experience level": "Entry Level",
            "seniority": "Entry Level",
            "salary": "40000-50000",
            "currency": "EUR",
            "notice period": "2 weeks",
            "gender": "Male",
            "ethnicity": "Prefer not to say",
            "how did you hear": "LinkedIn",
            "source": "LinkedIn",
            "referral": "LinkedIn",
        }

        for key, value in select_mapping.items():
            if key in label_lower:
                return value

        return ""

    def _resolve_radio_value(self, label: str) -> str:
        """For radio groups — return which option to select."""
        label_lower = label.lower()

        if any(k in label_lower for k in ["authorized", "right to work", "legally", "eligible to work"]):
            return "yes"
        if any(k in label_lower for k in ["require sponsor", "need sponsor", "visa sponsor"]):
            return "yes"
        if any(k in label_lower for k in ["relocate", "willing to move"]):
            return "no"
        if any(k in label_lower for k in ["remote", "work from home"]):
            return "hybrid"
        if any(k in label_lower for k in ["full.time", "employment type"]):
            return "full"
        if any(k in label_lower for k in ["currently employed", "are you employed"]):
            return "yes"
        if any(k in label_lower for k in ["disability"]):
            return "no"
        if any(k in label_lower for k in ["veteran"]):
            return "no"

        return ""


# ── Convenience wrapper for company-specific forms ──────────────────

async def fill_fidelity_talent_community(page: Page, profile: dict):
    """
    Specifically handles Fidelity's talent community form
    (talentcommunity.fidelity.com) which uses custom searchable
    multi-select dropdowns for Area of Interest etc.
    """
    from utils.helpers import human_delay, safe_fill

    print("  [Fidelity] Filling talent community form...")

    # Basic fields
    await safe_fill(page, 'input[name*="first"], input[placeholder*="First"]',
                    profile["preferred_name"], "first name")
    await human_delay(300, 600)
    await safe_fill(page, 'input[name*="last"], input[placeholder*="Last"]',
                    profile["last_name"], "last name")
    await human_delay(300, 600)
    await safe_fill(page, 'input[type="email"], input[name*="email"]',
                    profile["email"], "email")
    await human_delay(300, 600)
    await safe_fill(page, 'input[type="tel"], input[name*="phone"], input[name*="mobile"]',
                    profile["phone"], "phone")
    await human_delay(300, 600)
    await safe_fill(page, 'input[name*="location"], input[placeholder*="location"], input[placeholder*="Location"]',
                    "Dublin, Ireland", "location")
    await human_delay(400, 800)

    # Area of Interest — searchable multi-select
    filler = SmartFormFiller(page, profile, "Graduate Software Engineer", "Fidelity", "")
    await filler._fill_multi_select_checkboxes("area of interest", ["Technology"])
    await human_delay(500, 1000)

    print("  [Fidelity] Form filled.")

# Arabic & Emirati Text Policy (v1)

This policy governs every transcript in the dataset. It is enforced partly by
automated validation (see `backend/app/services/llm_scripts.py`) and partly by
reviewer discipline. Items marked **[decision]** are defaults chosen for v1 —
revisit them before large-scale recording if the target TTS framework demands
otherwise.

## 1. Dialect preservation (non-negotiable)

- Emirati wording is written **exactly as it is spoken**. It is never rewritten
  into Modern Standard Arabic for the training transcript.
  - ✅ `شو تبغي أسويلك؟`
  - ❌ `ماذا تريد أن أفعل لك؟`
- An MSA equivalent may be stored in `msa_equivalent` as supplementary
  metadata. It is never exported as the audio-paired text.

## 2. Two text layers per script

| Field           | Purpose                                | May contain digits/Latin |
|-----------------|----------------------------------------|--------------------------|
| `display_text`  | What the speaker reads on screen       | yes (natural writing)    |
| `training_text` | Exact verbalization paired with audio  | Latin yes, digits **no** |

If the script has no digits or special symbols, the two are identical.

## 3. Diacritics **[decision]**

- Transcripts are written **without tashkeel**, matching how Emirati text is
  naturally written and how most Arabic TTS corpora are prepared.
- Exception: a diacritic may be added to resolve a genuine ambiguity that
  changes pronunciation, sparingly and only in `training_text`.

## 4. Orthography & normalization **[decision]**

- Hamza/alef forms (أ إ آ), taa marbuta (ة), and alef maqsura (ى) are written
  correctly — the stored text is NOT normalized/folded.
- Character folding (alef unification, ة→ه, diacritic stripping) is applied
  only internally for duplicate detection and ASR comparison.
- Tatweel (ـ) is not used. Persian letters (پ چ گ ڤ) are not used; write the
  nearest Arabic letter unless a brand name requires otherwise.

## 5. Numbers, dates, times, prices, codes **[decision]**

- `display_text`: digits are fine (`24 ساعة`, `99 درهم`, `الساعة 5:30`).
- `training_text`: numbers are written **as the Arabic words the speaker will
  say**, in the dialect's natural reading: `أربعة وعشرين ساعة`,
  `تسعة وتسعين درهم`.
- Phone numbers / OTP codes read digit-by-digit are written digit-by-digit as
  words: `صفر خمسة صفر …`.
- The recording UI shows both layers so the speaker reads numbers consistently
  with the training text.

## 6. English words & code-switching **[decision]**

- English words spoken as English are kept in Latin script in both layers:
  `فعّلت باقة الـ data روماً جديدة` — do not transliterate to Arabic script.
- Abbreviations read letter-by-letter stay as capital letters (`SIM`, `5G`,
  `VAT`); the speaker reads them the way customers actually say them.
- Rationale: keeps a single consistent convention the TTS tokenizer can learn;
  revisit if the chosen model's tokenizer cannot handle Latin script.

## 7. Brand names & telecom terminology **[decision]**

- Brand names keep their official casing/spelling (`e&`, `du`, `eLife`,
  `5G`). Maintain the allowed-brand list in the generation dialog so the LLM
  only uses approved names.
- Arabic telecom vocabulary follows common Emirati usage: `باقة`, `رصيد`,
  `فاتورة`, `تغطية`, `اشتراك`.

## 8. Punctuation

- Keep natural punctuation (`،` `؟` `!` `.`) — it carries prosody cues.
- No decorative punctuation, no emojis, no quotation marks unless read aloud.

## 9. When the speaker deviates from the script

- Default action: **re-record** — the script bank stays the source of truth.
- If the deviation is natural and the take is otherwise excellent, the reviewer
  may edit the final transcript to match **exactly what was spoken** (accept
  with edit). The recording is then marked `text_edited=true` and the edited
  text is what gets exported.
- ASR output is advisory only. It never overwrites a transcript automatically.

## 10. Utterance length & delivery

- Target 3–12 s per clip (hard limits 0.8–25 s). One complete, natural
  utterance per clip — no mid-sentence cuts.
- Styles (`neutral`, `friendly`, `formal`, `apologetic`, `explanatory`,
  `energetic`) describe delivery; the speaker performs them, the text supports
  them.

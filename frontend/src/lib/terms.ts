/**
 * Term frequency over text already in the record.
 *
 * **This is not theme coding and must never be labelled as one.** There is no theme coder
 * in this project. `docs/framework/measurement.md` lists reasoning-theme coding as not
 * implemented, and states that when it exists it needs inter-coder agreement against a
 * hand-coded sample before any theme count appears in a claim. Counting words is not that,
 * and calling it that is precisely the overclaim the measurement document exists to prevent.
 *
 * What this does: lowercase, split on non-letters, drop stopwords, count. No stemming — a
 * stemmer would merge words a reader can see are different, which makes the counts harder
 * rather than easier to check.
 */

/**
 * English function words plus the terms this domain repeats so heavily that they crowd out
 * everything else. The domain list is deliberately short and named: removing "nuclear" from
 * a nuclear-strategy corpus is a judgement about the display, and it should be visible in
 * the source rather than buried in a generic list.
 */
const STOPWORDS = new Set([
  'a','about','above','after','again','against','all','also','am','an','and','any','are',
  'as','at','be','because','been','before','being','below','between','both','but','by',
  'can','cannot','could','did','do','does','doing','down','during','each','few','for',
  'from','further','had','has','have','having','he','her','here','hers','him','his','how',
  'i','if','in','into','is','it','its','itself','just','me','might','more','most','must',
  'my','no','nor','not','now','of','off','on','once','only','or','other','ought','our',
  'ours','out','over','own','rather','same','shall','she','should','so','some','such',
  'than','that','the','their','theirs','them','then','there','these','they','this','those',
  'through','to','too','under','until','up','upon','very','was','we','were','what','when',
  'where','which','while','who','whom','why','will','with','would','you','your','yours',
  'be','may','one','two','both','within','without','toward','towards','however','therefore',
  'thus','whether','given','make','makes','made','take','takes','use','used','using',
])

export const TERM_CLOUD_LABEL = 'Term frequency, not validated theme coding.'

export interface Term {
  term: string
  count: number
  /** Count relative to the most frequent term, for sizing. */
  weight: number
}

export function termFrequency(texts: string[], limit = 60, minLength = 4): Term[] {
  const counts = new Map<string, number>()
  for (const text of texts) {
    for (const word of text.toLowerCase().split(/[^a-z]+/)) {
      if (word.length < minLength || STOPWORDS.has(word)) continue
      counts.set(word, (counts.get(word) ?? 0) + 1)
    }
  }

  const ranked = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)

  const peak = ranked[0]?.[1] ?? 1
  return ranked.map(([term, count]) => ({ term, count, weight: count / peak }))
}

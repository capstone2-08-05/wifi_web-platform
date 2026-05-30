const AP_NAME_SUFFIX = /^AP-(\d+)$/i;

/** 기존 AP 이름에서 숫자 접미사 최댓값 + 1 → `AP-01` 형식. */
export function nextApSequentialName(existingNames: string[]): string {
  let max = 0;
  for (const raw of existingNames) {
    const m = AP_NAME_SUFFIX.exec(raw.trim());
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `AP-${String(max + 1).padStart(2, '0')}`;
}

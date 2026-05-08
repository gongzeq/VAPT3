// Tremor Raw chart utilities — copied 2026-05-07 from
// https://github.com/tremorlabs/tremor/tree/main/src/utils
// for trellis task 05-07-ocean-tech-frontend (PR2).
//
// Combines getYAxisDomain + hasOnlyOneValueForKey into a single helper
// module so the chart components have one less import target.

export const getYAxisDomain = (
  autoMinValue: boolean,
  minValue: number | undefined,
  maxValue: number | undefined,
) => {
  const minDomain = autoMinValue ? "auto" : (minValue ?? 0);
  const maxDomain = maxValue ?? "auto";
  return [minDomain, maxDomain];
};

/**
 * Returns true if the given array contains at most one entry that defines the
 * given key. Used by recharts wrappers to decide whether to render a series
 * as a single point (visual dot) instead of a line.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function hasOnlyOneValueForKey(array: any[], keyToCheck: string): boolean {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const val: any[] = [];
  for (const obj of array) {
    if (Object.prototype.hasOwnProperty.call(obj, keyToCheck)) {
      val.push(obj[keyToCheck]);
      if (val.length > 1) {
        return false;
      }
    }
  }
  return true;
}

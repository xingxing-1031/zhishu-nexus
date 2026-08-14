export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function readMigratedStorage(
  storage: StorageLike | undefined,
  primaryKey: string,
  legacyKey: string,
): string | null {
  if (!storage) return null;
  const current = storage.getItem(primaryKey);
  if (current !== null) return current;
  const legacy = storage.getItem(legacyKey);
  if (legacy !== null) storage.setItem(primaryKey, legacy);
  return legacy;
}

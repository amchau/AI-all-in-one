import "@testing-library/jest-dom/vitest";

const storageValues = new Map<string, string>();
const memoryStorage: Storage = {
	get length() {
		return storageValues.size;
	},
	clear() {
		storageValues.clear();
	},
	getItem(key) {
		return storageValues.get(key) ?? null;
	},
	key(index) {
		return Array.from(storageValues.keys())[index] ?? null;
	},
	removeItem(key) {
		storageValues.delete(key);
	},
	setItem(key, value) {
		storageValues.set(key, String(value));
	},
};

Object.defineProperty(window, "localStorage", {
	configurable: true,
	value: memoryStorage,
});
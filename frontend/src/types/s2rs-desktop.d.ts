export {};

type Unsubscribe = () => void;
type UpdaterInfo = { version?: string; releaseNotes?: string | Array<{ note?: string }>; releaseDate?: string };

declare global {
  interface Window {
    s2rsDesktop?: {
      updater?: {
        checkForUpdates(): Promise<unknown>;
        downloadUpdate(): Promise<unknown>;
        installUpdate(): Promise<unknown>;
        getAutoUpdateEnabled(): Promise<{ enabled: boolean; forcedDisabled?: boolean }>;
        setAutoUpdateEnabled(enabled: boolean): Promise<{ enabled: boolean; forcedDisabled?: boolean }>;
        onChecking(callback: () => void): Unsubscribe;
        onUpdateAvailable(callback: (info: UpdaterInfo) => void): Unsubscribe;
        onUpdateNotAvailable(callback: (info: UpdaterInfo) => void): Unsubscribe;
        onUpdateProgress(callback: (progress: { percent: number; transferred: number; total: number }) => void): Unsubscribe;
        onUpdateDownloaded(callback: (info: UpdaterInfo) => void): Unsubscribe;
        onUpdateError(callback: (error: { message: string }) => void): Unsubscribe;
      };
    };
  }
}

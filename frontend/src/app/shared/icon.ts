import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

// Stroke icons drawn in the mockups (24x24 viewBox).
const PATHS = {
  message: ['M4 5h16v11H9l-4 3v-3H4z', 'M8 9h8M8 12.5h5'],
  plus: ['M12 5v14M5 12h14'],
  check: ['m5 12 5 5L20 7'],
  clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3 2'],
  refresh: ['M21 12a9 9 0 1 1-2.6-6.4', 'M21 3v6h-6'],
  spinner: ['M21 12a9 9 0 1 1-2.6-6.4'],
  warning: ['M12 3 2 21h20L12 3z', 'M12 10v4m0 3v.5'],
  info: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 11v5m0-8v.5'],
  chevronRight: ['m9 6 6 6-6 6'],
  chevronLeft: ['m15 6-6 6 6 6'],
  chevronDown: ['m6 9 6 6 6-6'],
  first: ['m17 6-6 6 6 6M7 6v12'],
  last: ['m7 6 6 6-6 6M17 6v12'],
  arrowLeft: ['M19 12H5m0 0 6-6m-6 6 6 6'],
  upload: ['M12 16V4m0 0-4 4m4-4 4 4', 'M4 20h16'],
  folder: ['M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'],
  file: ['M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z', 'M14 3v6h6'],
  fileLines: [
    'M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z',
    'M14 3v6h6',
    'M8 13h8M8 17h5',
  ],
  close: ['M6 6l12 12M18 6 6 18'],
  play: ['M6 4l14 8-14 8z'],
  filter: ['M3 5h18l-7 8v6l-4 2v-8z'],
  search: ['M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z', 'm20 20-3.5-3.5'],
  copy: [
    'M11 9h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2z',
    'M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1',
  ],
  print: [
    'M6 9V3h12v6',
    'M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2',
    'M6 14h12v7H6z',
  ],
} as const;

export type IconName = keyof typeof PATHS;

@Component({
  selector: 'app-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.width]="size()"
      [attr.height]="size()"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      [attr.stroke-width]="strokeWidth()"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      [class.spin]="name() === 'spinner'"
    >
      @for (d of paths(); track $index) {
        <path [attr.d]="d" />
      }
    </svg>
  `,
  styles: `
    :host {
      display: inline-flex;
      flex: none;
    }
    .spin {
      animation: spin 1s linear infinite;
    }
    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
  `,
})
export class Icon {
  readonly name = input.required<IconName>();
  readonly size = input(18);
  readonly strokeWidth = input(2);
  protected readonly paths = computed(() => PATHS[this.name()]);
}

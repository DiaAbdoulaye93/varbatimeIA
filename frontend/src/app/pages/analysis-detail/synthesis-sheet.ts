import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { marked } from 'marked';

import { Icon } from '../../shared/icon';

const COPIED_FEEDBACK_MS = 2000;

/** Executive synthesis laid out as a report excerpt, with copy and print actions. */
@Component({
  selector: 'app-synthesis-sheet',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="head no-print">
      <div class="stack gap-1">
        <h2 class="section-title">Synthèse exécutive</h2>
        <p class="small muted">
          Extrait de rapport rédigé à partir des {{ nUsed() }} verbatims analysés, prêt à imprimer.
        </p>
      </div>
      <div class="row gap-2">
        <button type="button" class="btn btn-stroked" (click)="copy()">
          <app-icon [name]="copied() ? 'check' : 'copy'" />{{
            copied() ? 'Copié' : 'Copier le Markdown'
          }}
        </button>
        <button type="button" class="btn btn-stroked" (click)="print()">
          <app-icon name="print" />Imprimer
        </button>
      </div>
    </div>
    <article class="card sheet print-target">
      <header class="sheet-head">
        <p class="kicker">Synthèse exécutive · {{ name() }}</p>
        @if (context()) {
          <h3>{{ context() }}</h3>
        }
        <p class="meta">
          {{ nUsed() }} verbatims analysés · synthèse générée le {{ generatedOn() }}
        </p>
      </header>
      <div class="markdown" [innerHTML]="html()"></div>
      <footer class="sheet-foot">
        Synthèse générée automatiquement à partir des verbatims. À relire et contextualiser avant
        diffusion au client.
      </footer>
    </article>
  `,
  styleUrl: './synthesis-sheet.scss',
})
export class SynthesisSheet {
  private readonly document = inject(DOCUMENT);

  readonly markdown = input.required<string>();
  readonly name = input.required<string>();
  readonly context = input('');
  readonly nUsed = input.required<number>();
  readonly generatedOn = input.required<string>();

  protected readonly copied = signal(false);
  /** Angular sanitizes [innerHTML]: the model output cannot inject scripts. */
  protected readonly html = computed(() => marked.parse(this.markdown(), { async: false }));

  protected async copy(): Promise<void> {
    await navigator.clipboard.writeText(this.markdown());
    this.copied.set(true);
    setTimeout(() => this.copied.set(false), COPIED_FEEDBACK_MS);
  }

  protected print(): void {
    const body = this.document.body;
    body.classList.add('print-synthesis');
    const window = this.document.defaultView;
    window?.addEventListener('afterprint', () => body.classList.remove('print-synthesis'), {
      once: true,
    });
    window?.print();
  }
}

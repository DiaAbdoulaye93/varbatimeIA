import { HttpErrorResponse, HttpEventType } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { ACCEPT_ATTRIBUTE, ACCEPTED_FORMATS, FileInspection, inspectFile } from '../../core/file-inspect';
import { nameFromFilename } from '../../core/format';
import { ApiError } from '../../core/models';
import { Icon } from '../../shared/icon';

@Component({
  selector: 'app-analysis-new',
  imports: [RouterLink, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './analysis-new.html',
  styleUrl: './analysis-new.scss',
})
export class AnalysisNew {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly file = signal<File | null>(null);
  protected readonly inspection = signal<FileInspection | null>(null);
  protected readonly name = signal('');
  protected readonly context = signal('');
  protected readonly dragOver = signal(false);
  protected readonly uploading = signal(false);
  protected readonly uploadPct = signal(0);
  protected readonly serverError = signal<string | null>(null);
  protected readonly accept = ACCEPT_ATTRIBUTE;
  protected readonly acceptedFormats = ACCEPTED_FORMATS;
  private autoName = '';

  protected readonly fileError = computed(
    () => this.serverError() ?? this.inspection()?.error ?? null,
  );
  protected readonly canSubmit = computed(
    () => !!this.file() && !this.inspection()?.error && !this.uploading(),
  );

  protected async onFileInput(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) await this.select(file);
  }

  protected async onDrop(event: DragEvent): Promise<void> {
    event.preventDefault();
    this.dragOver.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) await this.select(file);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(true);
  }

  protected clearFile(): void {
    this.file.set(null);
    this.inspection.set(null);
    this.serverError.set(null);
    if (this.name() === this.autoName) this.name.set('');
  }

  protected onName(event: Event): void {
    this.name.set((event.target as HTMLInputElement).value);
  }

  protected onContext(event: Event): void {
    this.context.set((event.target as HTMLTextAreaElement).value);
  }

  protected submit(): void {
    const file = this.file();
    if (!file || !this.canSubmit()) return;
    this.uploading.set(true);
    this.uploadPct.set(0);
    this.serverError.set(null);
    this.api
      .createAnalysis(file, this.context(), this.name())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (event) => {
          if (event.type === HttpEventType.UploadProgress && event.total) {
            this.uploadPct.set(Math.round((100 * event.loaded) / event.total));
          } else if (event.type === HttpEventType.Response && event.body) {
            void this.router.navigate(['/analyses', event.body.id]);
          }
        },
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          const detail = (err.error as ApiError | null)?.detail;
          this.serverError.set(
            typeof detail === 'string'
              ? detail
              : "L'envoi a échoué. Vérifiez votre connexion et réessayez.",
          );
        },
      });
  }

  private async select(file: File): Promise<void> {
    this.serverError.set(null);
    this.file.set(file);
    this.inspection.set(await inspectFile(file));
    if (!this.name() || this.name() === this.autoName) {
      this.autoName = nameFromFilename(file.name);
      this.name.set(this.autoName);
    }
  }
}

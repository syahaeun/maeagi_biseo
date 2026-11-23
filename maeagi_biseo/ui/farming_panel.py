"""Review local farming history and delete selected completed sessions."""
import sqlite3
from datetime import datetime
from html import escape
from PySide6.QtCore import Qt, QDate, QLocale, QPoint, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QCalendarWidget, QScrollArea, QFrame, QStyle
from maeagi_biseo.core.farming import FarmingStore, KST, fragment_total
from maeagi_biseo.resources import tr
from maeagi_biseo.core.amounts import format_meso, format_fragments
from maeagi_biseo.ui.chat_theme import COLORS, appearance_for
from maeagi_biseo.ui.settings_widgets import Disclosure


def korea_today():
    return QDate.fromString(datetime.now(KST).date().isoformat(), Qt.ISODate)


class MonthPicker(QFrame):
    monthSelected = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName('farmingMonthPicker')
        self.setFixedWidth(304)
        self.year = korea_today().year()
        self.current = (self.year, korea_today().month())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(QLabel(tr('farming.choose_month')))
        header = QHBoxLayout()
        self.previous_year = QPushButton('‹')
        self.previous_year.setAccessibleName(tr('farming.previous_year'))
        self.previous_year.clicked.connect(lambda: self.change_year(-1))
        self.year_label = QLabel()
        self.year_label.setObjectName('farmingPickerYear')
        self.year_label.setAlignment(Qt.AlignCenter)
        self.next_year = QPushButton('›')
        self.next_year.setAccessibleName(tr('farming.next_year'))
        self.next_year.clicked.connect(lambda: self.change_year(1))
        for button in (self.previous_year, self.next_year):
            button.setFixedSize(32, 32)
        header.addWidget(self.previous_year)
        header.addWidget(self.year_label, 1)
        header.addWidget(self.next_year)
        layout.addLayout(header)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.month_buttons = []
        for month in range(1, 13):
            button = QPushButton(tr('farming.month_label', month=month))
            button.setObjectName('farmingMonthOption')
            button.setCheckable(True)
            button.setMinimumHeight(36)
            button.clicked.connect(lambda checked=False, value=month: self.choose(self.year, value))
            grid.addWidget(button, (month - 1) // 4, (month - 1) % 4)
            self.month_buttons.append(button)
        layout.addLayout(grid)
        self.this_month = QPushButton(tr('farming.this_month'))
        self.this_month.clicked.connect(lambda: self.choose(korea_today().year(), korea_today().month()))
        layout.addWidget(self.this_month)

    def change_year(self, delta):
        self.year = max(1, min(9999, self.year + delta))
        self.update_year()

    def update_year(self):
        self.year_label.setText(tr('farming.year_label', year=self.year))
        self.previous_year.setEnabled(self.year > 1)
        self.next_year.setEnabled(self.year < 9999)
        for month, button in enumerate(self.month_buttons, 1):
            button.setChecked((self.year, month) == self.current)

    def choose(self, year, month):
        self.hide()
        self.monthSelected.emit(year, month)

    def open_for(self, anchor, year, month):
        from maeagi_biseo.ui.chat_theme import apply_chat_theme
        apply_chat_theme(self, appearance_for(anchor))
        self.year, self.current = year, (year, month)
        self.update_year()
        self.adjustSize()
        point = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        bounds = anchor.screen().availableGeometry()
        point.setX(max(bounds.left(), min(point.x(), bounds.right() - self.width() + 1)))
        if point.y() + self.height() > bounds.bottom() + 1:
            point.setY(anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 6)
        point.setY(max(bounds.top(), point.y()))
        self.move(point)
        self.show()
        self.month_buttons[month - 1].setFocus()


class FarmingCalendar(QCalendarWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.days = {}
        self.setObjectName('farmingCalendar')
        self.setLocale(QLocale(QLocale.Korean, QLocale.SouthKorea))
        self.setFirstDayOfWeek(Qt.Sunday)
        self.setNavigationBarVisible(False)
        self.setDateEditEnabled(False)
        self.setSelectedDate(korea_today())
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.setGridVisible(True)
        self.setMinimumHeight(340)

    def paintCell(self, painter, rect, day):
        painter.save()
        selected = day == self.selectedDate()
        colors = COLORS[appearance_for(self)]
        sessions = self.days.get(day.toString(Qt.ISODate), [])
        background = 'accent' if selected else 'user' if sessions else 'surface'
        painter.fillRect(rect, QColor(colors[background]))
        painter.setPen(QColor(colors['line']))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.setPen(QColor(colors['accent_text' if selected else
                                     'text' if day.month() == self.monthShown() else 'muted']))
        font = painter.font()
        font.setBold(day == korea_today())
        painter.setFont(font)
        painter.drawText(rect.adjusted(5, 2, -5, -2), Qt.AlignTop | Qt.AlignLeft, str(day.day()))
        if sessions:
            font.setBold(False)
            font.setPointSizeF(max(7, font.pointSizeF() - 1))
            painter.setFont(font)
            text = tr('farming.calendar_cell', count=len(sessions),
                      meso=format_meso(sum(row['meso_change'] for row in sessions), signed=True))
            lines = text.split('\n')
            metrics = painter.fontMetrics()
            for index, line in enumerate(lines):
                y = rect.bottom() - (len(lines) - index) * metrics.height()
                painter.drawText(rect.x() + 5, y, rect.width() - 10, metrics.height(),
                                 Qt.AlignLeft | Qt.AlignVCenter,
                                 metrics.elidedText(line, Qt.ElideRight, max(1, rect.width() - 10)))
        painter.restore()


class FarmingPanel(QWidget):
    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self.store = store or FarmingStore()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setProperty('settingsPanel', True)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content.setObjectName('settingsPage')
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        help_text = QLabel(tr('farming.help'))
        help_text.setWordWrap(True)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.calendar = FarmingCalendar()
        self.calendar.selectionChanged.connect(self.show_selected_day)
        self.calendar.currentPageChanged.connect(self.refresh)
        toolbar = QHBoxLayout()
        self.month_button = QPushButton()
        self.month_button.setObjectName('farmingMonthTrigger')
        self.month_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        self.month_button.setLayoutDirection(Qt.RightToLeft)
        self.month_button.setAccessibleName(tr('farming.choose_month'))
        self.month_picker = MonthPicker(self)
        self.month_button.clicked.connect(self.open_month_picker)
        self.month_picker.monthSelected.connect(self.select_month)
        toolbar.addWidget(self.month_button)
        self.previous_month = QPushButton('‹')
        self.previous_month.setAccessibleName(tr('farming.previous_month'))
        self.previous_month.clicked.connect(self.calendar.showPreviousMonth)
        self.next_month = QPushButton('›')
        self.next_month.setAccessibleName(tr('farming.next_month'))
        self.next_month.clicked.connect(self.calendar.showNextMonth)
        for button in (self.previous_month, self.next_month):
            button.setFixedWidth(34)
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.today_button = QPushButton(tr('farming.today'))
        self.today_button.setObjectName('farmingToday')
        self.today_button.clicked.connect(lambda: self.calendar.setSelectedDate(korea_today()))
        toolbar.addWidget(self.today_button)
        self.refresh_button = QPushButton(tr('farming.refresh'))
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)
        layout.addWidget(self.calendar, 3)
        self.day_summary = QLabel()
        self.day_summary.setObjectName('captureHeading')
        self.day_summary.setWordWrap(True)
        layout.addWidget(self.day_summary)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName('farmingTable')
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(62)
        self.table.setHorizontalHeaderLabels([tr('farming.column_' + key) for key in ('start', 'end', 'time', 'meso', 'fragments')])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setMouseTracking(True)
        self.table.itemSelectionChanged.connect(self.update_delete_button)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.resize_record_table()
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.delete_button = QPushButton(tr('farming.delete_selected'))
        self.delete_button.setObjectName('deleteFarmingRecords')
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_selected)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        layout.addWidget(Disclosure(tr('farming.guide'), help_text))
        location = QLabel(tr('farming.location', path=str(self.store.path)))
        location.setWordWrap(True)
        location.setTextInteractionFlags(location.textInteractionFlags() | Qt.TextSelectableByMouse)
        layout.addWidget(location)

    def open_month_picker(self):
        if self.month_picker.isVisible():
            self.month_picker.hide()
        else:
            self.month_picker.open_for(self.month_button, self.calendar.yearShown(), self.calendar.monthShown())

    def select_month(self, year, month):
        self.calendar.setSelectedDate(QDate(year, month, 1))
        self.month_button.setFocus()

    def hideEvent(self, event):
        self.month_picker.hide()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.resize_record_table()
        self.refresh()

    def resize_record_table(self):
        header = self.table.horizontalHeader()
        self.table.setMinimumHeight(max(header.height(), header.sizeHint().height()) +
            self.table.verticalHeader().defaultSectionSize() * 3 +
            self.table.frameWidth() * 2 + self.table.horizontalScrollBar().sizeHint().height())

    def refresh(self, *args):
        try:
            first = QDate(self.calendar.yearShown(), self.calendar.monthShown(), 1)
            self.month_button.setText(tr('farming.month_trigger', year=first.year(), month=first.month()))
            last = first.addMonths(1).addDays(-1)
            result = self.store.query(since=first.toString(Qt.ISODate), until=last.toString(Qt.ISODate))
            active = result['active']
            text = tr('farming.month_heading', year=first.year(), month=first.month()) + '\n' + tr('farming.history_summary', count=result['completed_sessions'], minutes=round(result['total_seconds'] / 60, 1),
                      meso=format_meso(result['meso_change'], signed=True), fragments=format_fragments(result['fragment_change'], signed=True))
            if active:
                text += '\n' + tr('farming.active_summary', started=self.display_time(active['started_at']).replace('\n', ' '), meso=format_meso(active['start_meso']), fragments=format_fragments(active['start_fragments']))
            self.summary.setText(text)
            self.calendar.days = {}
            for session in result['sessions']:
                day = datetime.fromisoformat(session['ended_at']).astimezone(KST).date().isoformat()
                self.calendar.days.setdefault(day, []).append(session)
            self.calendar.updateCells()
            selected = self.calendar.selectedDate()
            if (selected.year(), selected.month()) != (first.year(), first.month()):
                self.calendar.setSelectedDate(first)
            else:
                self.show_selected_day()
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.summary.setText(tr('farming.error_receipt', error=str(exc)))

    def show_selected_day(self):
        day = self.calendar.selectedDate().toString(Qt.ISODate)
        sessions = self.calendar.days.get(day, [])
        self.day_summary.setText(tr('farming.day_summary', date=day, count=len(sessions),
            minutes=round(sum(row['duration_seconds'] for row in sessions) / 60, 1),
            meso=format_meso(sum(row['meso_change'] for row in sessions), signed=True),
            fragments=format_fragments(fragment_total(sessions), signed=True)) if sessions else
            tr('farming.day_empty', date=day))
        self.table.clearSelection()
        self.table.setRowCount(len(sessions))
        for row, session in enumerate(sessions):
            tooltip = self.session_tooltip(session)
            values = [self.display_time(session['started_at']), self.display_time(session['ended_at']), str(round(session['duration_seconds'] / 60, 1)),
                      format_meso(session['meso_change'], signed=True),
                      '—' if session['fragment_change'] is None else f"{session['fragment_change']:+}"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, session['id'])
                item.setToolTip(tooltip)
                self.table.setItem(row, column, item)
        self.update_delete_button()

    @staticmethod
    def display_time(value):
        return datetime.fromisoformat(value).astimezone(KST).strftime('%Y.%m.%d\n%H:%M:%S')

    @staticmethod
    def session_tooltip(session):
        hours, remainder = divmod(session['duration_seconds'], 3600)
        minutes, seconds = divmod(remainder, 60)
        text = tr('farming.record_tooltip',
                  started=FarmingPanel.display_time(session['started_at']).replace('\n', ' '),
                  ended=FarmingPanel.display_time(session['ended_at']).replace('\n', ' '),
                  hours=hours, minutes=minutes, seconds=seconds,
                  start_meso=format_meso(session['start_meso']), end_meso=format_meso(session['end_meso']),
                  meso_change=format_meso(session['meso_change'], signed=True),
                  start_fragments=format_fragments(session['start_fragments']),
                  end_fragments=format_fragments(session['end_fragments']),
                  fragment_change=format_fragments(session['fragment_change'], signed=True))
        if session.get('note'):
            text += '\n\n' + tr('farming.record_note', note=session['note'])
        # Notes are user data, never interpreted as tooltip HTML.
        return '<qt>' + escape(text).replace('\n', '<br>') + '</qt>'

    def selected_ids(self):
        return [self.table.item(index.row(), 0).data(Qt.UserRole)
                for index in self.table.selectionModel().selectedRows()]

    def update_delete_button(self):
        self.delete_button.setEnabled(bool(self.selected_ids()))

    def delete_selected(self):
        identifiers = self.selected_ids()
        if not identifiers:
            return
        confirmation = QMessageBox(self)
        confirmation.setWindowTitle(tr('farming.delete_title'))
        confirmation.setIcon(QMessageBox.Warning)
        confirmation.setText(tr('farming.delete_confirm', count=len(identifiers)))
        confirmation.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        confirmation.button(QMessageBox.Yes).setText(tr('farming.delete_selected'))
        confirmation.button(QMessageBox.No).setText(tr('common.cancel'))
        confirmation.setDefaultButton(QMessageBox.No)
        if confirmation.exec() != QMessageBox.Yes:
            return
        try:
            count = self.store.delete_completed(identifiers)
            self.refresh()
            self.notice.setText(tr('farming.delete_done', count=count))
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.notice.setText(tr('farming.error_receipt', error=str(exc)))

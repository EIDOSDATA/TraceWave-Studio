/** @file @brief wxWidgets 대화상자에서 Windows 교환 파일 저장을 연결한다. */
#include "network_export.h"
#include "file_delivery.h"
#include "network_export_files.h"
#include "studio_support.h"

#include <wx/filedlg.h>
#include <wx/msgdlg.h>

void WriteExternalExportFile(const wxString& path, const wxString& workspace, const std::string& bytes)
{
    NetworkExportFiles::WriteExternal(path.ToStdWstring(), workspace.ToStdWstring(), bytes);
}

void WriteNetworkExportFiles(const Json& result, const wxString& path, const wxString& workspace)
{
    NetworkExportFiles::WriteResult(result, path.ToStdWstring(), workspace.ToStdWstring());
}

bool SaveNetworkExport(wxWindow* parent, const Json& result, const wxString& workspace)
{
    try
    {
        wxFileDialog chooser(parent, Display("복소 자료 내보내기"), wxEmptyString,
                             Display(result.at("file_name").get<std::string>()), Display("교환 파일 (*.*)|*.*"),
                             wxFD_SAVE);
        if (chooser.ShowModal() != wxID_OK)
        {
            return false;
        }
        WriteNetworkExportFiles(result, chooser.GetPath(), workspace);
        wxMessageBox(Display("교환 파일과 .conditions.json 조건 파일을 함께 저장했습니다.\nCSV 단독 재가져오기는 "
                             "기준면/Z0 전체 조건을 복원하지 않습니다. 전체 자료 교환에는 HDF5를 사용하세요."),
                     Display("내보내기 완료"), wxOK | wxICON_INFORMATION, parent);
        return true;
    }
    catch (const std::exception& error)
    {
        wxMessageBox(Display(error.what()), Display("내보내기를 완료하지 못함"), wxOK | wxICON_ERROR, parent);
        return false;
    }
}

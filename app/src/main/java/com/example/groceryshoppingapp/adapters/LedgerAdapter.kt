//package com.example.groceryshoppingapp
//
//import android.view.LayoutInflater
//import android.view.View
//import android.view.ViewGroup
//import android.widget.TextView
//import androidx.recyclerview.widget.RecyclerView
//import com.example.groceryshoppingapp.models.Ledger
//
//class LedgerAdapter(private val ledgerList: List<Ledger>) :
//    RecyclerView.Adapter<LedgerAdapter.ViewHolder>() {
//
//    inner class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
//        val txtType: TextView = itemView.findViewById(R.id.txtLedgerType)
//        val txtAmount: TextView = itemView.findViewById(R.id.txtLedgerAmount)
//        val txtRemarks: TextView = itemView.findViewById(R.id.txtLedgerRemarks)
//    }
//
//    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
//        val view = LayoutInflater.from(parent.context)
//            .inflate(R.layout.item_ledger, parent, false)
//        return ViewHolder(view)
//    }
//
//    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
//        val item = ledgerList[position]
//        holder.txtType.text = item.type
//        holder.txtAmount.text = "₹${item.totalAmount} (Paid ₹${item.paidAmount})"
//        holder.txtRemarks.text = item.remarks
//    }
//
//    override fun getItemCount() = ledgerList.size
//}
